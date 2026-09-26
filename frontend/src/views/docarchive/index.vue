<template>
  <section class="page" data-module="docarchive">
    <header class="page-head">
      <div>
        <h2>单证材料归档</h2>
        <p class="page-desc">随附材料按单证编号归档并记版本；旧版本仅可查看，材料可按航次打包取走。</p>
      </div>
      <div class="page-actions">
        <select v-model="packageVoyage" class="voyage-select">
          <option value="" disabled>选择航次</option>
          <option v-for="item in voyageOptions" :key="item" :value="item">{{ item }}</option>
        </select>
        <button class="btn primary" type="button" :disabled="!packageVoyage" @click="downloadPackage">
          按航次打包取走
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="panel">
      <h3 class="panel-title">交单归档（一次可交多份，逐份回执）</h3>
      <div v-for="(row, index) in submitRows" :key="index" class="submit-row">
        <input
          v-model="row.docNo"
          list="manifest-doc-options"
          class="doc-input"
          placeholder="单证编号，如 MANI-0001"
        />
        <label class="file-picker">
          <input type="file" multiple @change="onFiles(index, $event)" />
          <span>选择材料</span>
        </label>
        <span class="file-names">
          {{ row.files.length ? `已选 ${row.files.length} 份：${row.files.map((f) => f.name).join('、')}` : '未选材料' }}
        </span>
        <input v-model="row.remark" class="remark-input" placeholder="备注（可选）" />
        <button class="btn ghost" type="button" @click="removeRow(index)">移除</button>
      </div>
      <datalist id="manifest-doc-options">
        <option v-for="opt in manifestOptions" :key="opt.docNo" :value="opt.docNo">
          {{ opt.status }}
        </option>
      </datalist>
      <div class="submit-actions">
        <button class="btn" type="button" @click="addRow">再加一份</button>
        <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
          {{ submitting ? '提交中…' : '提交归档' }}
        </button>
      </div>
      <ul v-if="receipts.length" class="receipt-list">
        <li v-for="receipt in receipts" :key="receipt.doc_no + receipt.message" :class="receipt.ok ? 'receipt-ok' : 'receipt-bad'">
          {{ receipt.message }}
        </li>
      </ul>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>单证编号</span>
        <input v-model="filters.keyword" placeholder="按单证编号检索" />
      </label>
      <label class="filter-item">
        <span>关联航次</span>
        <select v-model="filters.voyage">
          <option value="">全部航次</option>
          <option v-for="item in voyageOptions" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>单证编号</th>
          <th>单证类型</th>
          <th>关联航次</th>
          <th>当前版本</th>
          <th>版本数</th>
          <th>材料份数</th>
          <th>最近提交时间</th>
          <th>单证状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.doc_no">
          <td>{{ row.doc_no }}</td>
          <td>{{ row.doc_type || '—' }}</td>
          <td>{{ row.voyage || '—' }}</td>
          <td>v{{ row.latest_version }}</td>
          <td>{{ row.version_count }}</td>
          <td>{{ row.file_count }}</td>
          <td>{{ row.last_submit }}</td>
          <td>{{ row.manifest_status }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openVersions(row.doc_no)">版本与材料</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="9" class="empty-state">暂无归档材料，可先在上方交单归档</td>
        </tr>
      </tbody>
    </table>

    <section v-if="activeDoc" class="panel">
      <h3 class="panel-title">
        {{ activeDoc }} 的版本记录
        <button class="link" type="button" @click="closeVersions">收起</button>
      </h3>
      <div v-for="version in versions" :key="version.version" class="version-block">
        <header class="version-head">
          <strong>v{{ version.version }}</strong>
          <span v-if="version.downloadable" class="tag tag-current">当前版本</span>
          <span v-else class="tag tag-old">旧版本 · 仅可查看</span>
          <span class="version-meta">{{ version.created_at }} 提交</span>
          <span v-if="version.remark" class="version-meta">备注：{{ version.remark }}</span>
        </header>
        <table class="data-table">
          <thead>
            <tr><th>文件名</th><th>大小</th><th>校验（SHA256 前 12 位）</th><th>可执行动作</th></tr>
          </thead>
          <tbody>
            <tr v-for="file in version.files" :key="file.id">
              <td>{{ file.name }}</td>
              <td>{{ formatSize(file.size) }}</td>
              <td>{{ file.sha256.slice(0, 12) }}</td>
              <td class="row-actions">
                <button class="link" type="button" @click="previewFile(version.version, file)">查看</button>
                <button
                  v-if="version.downloadable"
                  class="link"
                  type="button"
                  @click="downloadFile(version.version, file)"
                >
                  下载
                </button>
                <span v-else class="muted-text">不可下载</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="preview" class="panel">
      <h3 class="panel-title">
        查看 {{ preview.name }}（{{ preview.doc_no }} v{{ preview.version }}）
        <button class="link" type="button" @click="preview = null">收起</button>
      </h3>
      <pre class="preview-box">{{ preview.text }}</pre>
      <p v-if="preview.truncated" class="muted-text">内容较长，仅显示前 8KB。</p>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 份归档单证</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/docarchive'

type DocRow = {
  doc_no: string
  doc_type: string
  voyage: string
  latest_version: number
  version_count: number
  file_count: number
  last_submit: string
  manifest_status: string
}
type Receipt = { doc_no: string; ok: boolean; version: number | null; message: string; missing: string[] }
type SubmitRow = { docNo: string; remark: string; files: File[] }
type VersionFile = { id: number; name: string; size: number; sha256: string; created_at: string }
type VersionRow = {
  version: number
  voyage: string
  doc_type: string
  remark: string
  created_at: string
  downloadable: boolean
  files: VersionFile[]
}
type Preview = { doc_no: string; version: number; name: string; size: number; sha256: string; text: string; truncated: boolean }

const stats = ref([
  { label: '归档单证', value: 0 },
  { label: '版本总数', value: 0 },
  { label: '材料份数', value: 0 },
  { label: '涉及航次', value: 0 },
])
const rows = ref<DocRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', voyage: '' })
const voyageOptions = ref<string[]>([])
const packageVoyage = ref('')
const manifestOptions = ref<{ docNo: string; status: string }[]>([])

const submitRows = ref<SubmitRow[]>([{ docNo: '', remark: '', files: [] }])
const submitting = ref(false)
const receipts = ref<Receipt[]>([])

const activeDoc = ref('')
const versions = ref<VersionRow[]>([])
const preview = ref<Preview | null>(null)

function formatSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

function addRow() {
  submitRows.value.push({ docNo: '', remark: '', files: [] })
}

function removeRow(index: number) {
  submitRows.value.splice(index, 1)
  if (!submitRows.value.length) addRow()
}

function onFiles(index: number, event: Event) {
  const input = event.target as HTMLInputElement
  submitRows.value[index].files = Array.from(input.files ?? [])
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? '').split(',')[1] ?? '')
    reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
}

async function submitBatch() {
  errorMessage.value = ''
  receipts.value = []
  submitting.value = true
  try {
    const items = []
    for (const row of submitRows.value) {
      const materials = []
      for (const file of row.files) {
        materials.push({ name: file.name, content_base64: await readFile(file) })
      }
      items.push({ doc_no: row.docNo.trim(), remark: row.remark.trim(), materials })
    }
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '提交未送达，请稍后重试')
    }
    receipts.value = payload.receipts ?? []
    submitRows.value = [{ docNo: '', remark: '', files: [] }]
    await Promise.all([reload(), loadSummary(), loadVoyages()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交归档失败'
  } finally {
    submitting.value = false
  }
}

async function openVersions(docNo: string) {
  errorMessage.value = ''
  preview.value = null
  try {
    const response = await request(`${ENDPOINT}/documents/${encodeURIComponent(docNo)}/versions`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '版本记录读取失败')
    }
    activeDoc.value = docNo
    versions.value = payload.versions ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本记录读取失败'
  }
}

function closeVersions() {
  activeDoc.value = ''
  versions.value = []
  preview.value = null
}

function downloadFile(version: number, file: VersionFile) {
  const url = `${ENDPOINT}/documents/${encodeURIComponent(activeDoc.value)}/versions/${version}/files/${file.id}/download`
  window.open(url, '_blank')
}

async function previewFile(version: number, file: VersionFile) {
  errorMessage.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/documents/${encodeURIComponent(activeDoc.value)}/versions/${version}/files/${file.id}/preview`,
    )
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '材料内容读取失败')
    }
    preview.value = payload
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '材料内容读取失败'
  }
}

async function downloadPackage() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/voyages/${encodeURIComponent(packageVoyage.value)}/package`)
    if (!response.ok) {
      const payload = await response.json()
      throw new Error(payload.detail ?? '打包失败，请稍后重试')
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${packageVoyage.value}_材料包.zip`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '按航次打包失败'
  }
}

function resetFilters() {
  filters.value = { keyword: '', voyage: '' }
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.voyage) query.set('voyage', filters.value.voyage)
  query.set('size', '50')
  try {
    const response = await request(`${ENDPOINT}/documents?${query.toString()}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '归档列表读取失败')
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归档列表读取失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    const payload = await response.json()
    stats.value = [
      { label: '归档单证', value: payload.documents ?? 0 },
      { label: '版本总数', value: payload.versions ?? 0 },
      { label: '材料份数', value: payload.files ?? 0 },
      { label: '涉及航次', value: payload.voyages ?? 0 },
    ]
  } catch {
    // 看板数字拿不到时保留 0，不挡主流程
  }
}

async function loadVoyages() {
  try {
    const response = await request(`${ENDPOINT}/voyages`)
    const payload = await response.json()
    voyageOptions.value = payload.items ?? []
  } catch {
    voyageOptions.value = []
  }
}

async function loadManifestOptions() {
  try {
    const response = await request('/api/manifest?size=200')
    const payload = await response.json()
    manifestOptions.value = (payload.items ?? []).map((item: Record<string, string>) => ({
      docNo: item['单证编号'],
      status: item.status ?? '',
    }))
  } catch {
    manifestOptions.value = []
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
  void loadVoyages()
  void loadManifestOptions()
})
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  margin: 0 0 10px;
}
.submit-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.doc-input { width: 180px; }
.remark-input { width: 160px; }
.file-names { color: var(--muted); font-size: 12px; }
.file-picker input { display: none; }
.file-picker span {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  background: #fff;
}
.submit-actions { display: flex; gap: 8px; }
.receipt-list { list-style: none; padding: 0; margin: 10px 0 0; }
.receipt-list li { padding: 6px 10px; border-radius: 6px; margin-bottom: 4px; font-size: 13px; }
.receipt-ok { background: #ecfdf3; color: #067647; }
.receipt-bad { background: #fef3f2; color: #b42318; }
.voyage-select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.page-actions { display: flex; gap: 8px; }
.version-block { margin-bottom: 12px; }
.version-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.version-meta { color: var(--muted); font-size: 12px; }
.tag { font-size: 12px; border-radius: 4px; padding: 2px 6px; }
.tag-current { background: #ecfdf3; color: #067647; }
.tag-old { background: #f2f4f7; color: var(--muted); }
.muted-text { color: var(--muted); font-size: 12px; }
.preview-box {
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
}
</style>
