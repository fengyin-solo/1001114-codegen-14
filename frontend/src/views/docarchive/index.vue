<template>
  <section class="page" data-module="docarchive">
    <header class="page-head">
      <div>
        <h2>单证材料归档</h2>
        <p class="page-desc">随附材料按单证编号归档记版本：整批提交逐份回执，缺漏先挡下列明再补；旧版本可查看不再下载，材料可按航次打包取走。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showSubmit = !showSubmit">
          {{ showSubmit ? '收起提交面板' : '批量交材料' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出归档清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>单证编号</span>
        <input v-model="filters.keyword" class="input" placeholder="按单证编号检索" />
      </label>
      <label class="filter-item">
        <span>关联航次</span>
        <input v-model="filters.voyage" class="input" placeholder="按航次检索" />
      </label>
      <label class="filter-item">
        <span>归档状态</span>
        <select v-model="filters.status" class="input">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <label class="filter-item">
        <span>按航次打包取走</span>
        <span class="package-bar">
          <input v-model="packageVoyageNo" class="input" placeholder="航次编号，如 VOYA-0001" />
          <button class="btn" type="button" @click="packageVoyage">打包下载</button>
        </span>
      </label>
    </form>

    <section v-if="showSubmit" class="panel">
      <div class="panel-head">
        <h3 class="panel-title">批量交材料：一次可交多份，逐份回执；任何一份有缺漏，整批先挡下</h3>
        <label class="form-item">
          <span>提交人</span>
          <input v-model="submitOperator" class="input" placeholder="提交人姓名" />
        </label>
      </div>
      <div v-for="(item, idx) in submitItems" :key="idx" class="submit-item">
        <div class="form-grid">
          <label class="form-item">
            <span>单证编号 *</span>
            <input v-model="item.单证编号" class="input" placeholder="须是单证处理里已有的编号" />
          </label>
          <label class="form-item">
            <span>关联航次</span>
            <input v-model="item.关联航次" class="input" placeholder="留空则从单证带出" />
          </label>
          <label class="form-item grow">
            <span>说明</span>
            <input v-model="item.说明" class="input" placeholder="本次交材料的说明" />
          </label>
          <button class="btn ghost" type="button" @click="removeItem(idx)">移除此份</button>
        </div>
        <div v-for="(mat, midx) in item.材料" :key="midx" class="material-row">
          <input v-model="mat.名称" class="input" placeholder="材料名称" />
          <input v-model="mat.类型" class="input" list="material-types" placeholder="材料类型" />
          <input v-model="mat.内容" class="input mat-content" placeholder="材料内容（文本）" />
          <button class="btn ghost" type="button" @click="removeMaterial(idx, midx)">删</button>
        </div>
        <datalist id="material-types">
          <option v-for="t in materialTypes" :key="t" :value="t" />
        </datalist>
        <button class="btn ghost" type="button" @click="addMaterial(idx)">+ 加一份材料</button>
      </div>
      <div class="panel-actions">
        <button class="btn" type="button" @click="addItem">+ 再加一份单证</button>
        <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
          {{ submitting ? '提交中…' : '提交整批' }}
        </button>
      </div>
      <p v-if="submitMessage" class="panel-message" :class="{ 'error-text': !submitOk }">{{ submitMessage }}</p>
      <table v-if="receipts.length" class="data-table">
        <thead>
          <tr><th>回执编号</th><th>单证编号</th><th>结果</th><th>版本号</th><th>缺少材料</th><th>说明</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="receipt in receipts" :key="receipt.回执编号">
            <td>{{ receipt.回执编号 }}</td>
            <td>{{ receipt.单证编号 }}</td>
            <td :class="receipt.结果 === '已归档' ? 'receipt-ok' : 'receipt-blocked'">{{ receipt.结果 }}</td>
            <td>{{ receipt.版本号 ?? '—' }}</td>
            <td>{{ receipt.缺少材料.length ? receipt.缺少材料.join('、') : '—' }}</td>
            <td>{{ receipt.说明 }}</td>
            <td>{{ receipt.时间 }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openVersions(row)">版本记录</button>
            <button class="link" type="button" @click="downloadCurrent(row)">下载当前版</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无归档记录，可点「批量交材料」提交</td>
        </tr>
      </tbody>
    </table>

    <section v-if="activeDetail" class="panel">
      <div class="panel-head">
        <h3 class="panel-title">{{ activeDetail.单证编号 }} 的版本记录（当前 v{{ activeDetail.当前版本 }}）</h3>
        <button class="btn ghost" type="button" @click="activeDetail = null">收起</button>
      </div>
      <div v-for="ver in sortedVersions" :key="ver.version" class="version-card">
        <div class="version-head">
          <span>
            <strong>v{{ ver.version }}</strong>
            <span class="tag" :class="{ readonly: !ver.可取 }">{{ ver.可取 ? '当前版' : '旧版 · 仅可查看' }}</span>
            <span class="version-time">{{ ver.上传时间 }}</span>
            <span v-if="ver.说明" class="version-note">{{ ver.说明 }}</span>
          </span>
          <button v-if="ver.可取" class="btn" type="button" @click="downloadVersion(ver.version)">下载此版</button>
          <span v-else class="version-readonly">旧版本仅可查看，不能再下载</span>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>材料名称</th><th>类型</th><th>内容</th></tr>
          </thead>
          <tbody>
            <tr v-for="(mat, midx) in ver.材料" :key="midx">
              <td>{{ mat.名称 }}</td>
              <td>{{ mat.类型 }}</td>
              <td>{{ mat.内容 || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条归档记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & { id: number }

interface Material {
  名称: string
  类型: string
  内容: string
}

interface SubmitItem {
  单证编号: string
  关联航次: string
  说明: string
  材料: Material[]
}

interface Receipt {
  回执编号: string
  单证编号: string
  结果: string
  版本号: number | null
  缺少材料: string[]
  说明: string
  时间: string
}

interface VersionRecord {
  version: number
  上传时间: string
  说明: string
  可取: boolean
  材料: Material[]
}

interface ArchiveDetail {
  id: number
  单证编号: string
  关联航次: string
  当前版本: number
  status: string
  versions: VersionRecord[]
}

const ENDPOINT = '/api/docarchive'
const columns = ['单证编号', '关联航次', '当前版本', '材料份数', '提交人', '归档时间', '审核人员', '归档状态', '版本数']
const actions = ['审核通过', '退回材料']
const statuses = ['待审核', '已审核', '已退回']
const materialTypes = ['单证正文', '随附清单', '舱单', '提单', '装箱单', '报关单']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', voyage: '', status: '' })
const stats = ref([
  { label: '待审核材料', value: 0 },
  { label: '已审核材料', value: 0 },
  { label: '历史版本（仅查看）', value: 0 },
])

const showSubmit = ref(false)
const submitting = ref(false)
const submitOperator = ref('')
const submitItems = ref<SubmitItem[]>([])
const submitMessage = ref('')
const submitOk = ref(false)
const receipts = ref<Receipt[]>([])
const packageVoyageNo = ref('')
const activeDetail = ref<ArchiveDetail | null>(null)

const sortedVersions = computed(() =>
  activeDetail.value ? [...activeDetail.value.versions].sort((a, b) => b.version - a.version) : [],
)

function blankItem(): SubmitItem {
  return {
    单证编号: '',
    关联航次: '',
    说明: '',
    材料: [
      { 名称: '', 类型: '单证正文', 内容: '' },
      { 名称: '', 类型: '随附清单', 内容: '' },
    ],
  }
}

function addItem() {
  submitItems.value.push(blankItem())
}

function removeItem(idx: number) {
  submitItems.value.splice(idx, 1)
}

function addMaterial(idx: number) {
  submitItems.value[idx]?.材料.push({ 名称: '', 类型: '', 内容: '' })
}

function removeMaterial(idx: number, midx: number) {
  submitItems.value[idx]?.材料.splice(midx, 1)
}

function resetFilters() {
  filters.value = { keyword: '', voyage: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitBatch() {
  errorMessage.value = ''
  submitMessage.value = ''
  receipts.value = []
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/submit`, {
      method: 'POST',
      body: JSON.stringify({ 提交人: submitOperator.value, items: submitItems.value }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string; 回执?: Receipt[] }
    submitOk.value = payload.ok
    submitMessage.value = payload.message
    receipts.value = payload.回执 ?? []
    if (payload.ok) {
      submitItems.value = [blankItem()]
      await Promise.all([reload(), loadStats()])
    }
  } catch (error) {
    submitOk.value = false
    submitMessage.value = error instanceof Error ? error.message : '批量提交失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!payload.ok) {
      throw new Error(payload.message || '归档动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
    if (activeDetail.value?.id === row.id) {
      await openVersions(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归档操作失败'
  }
}

async function openVersions(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('版本记录读取失败')
    }
    activeDetail.value = (await response.json()) as ArchiveDetail
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本记录读取失败'
  }
}

async function downloadZip(url: string, fallbackName: string) {
  errorMessage.value = ''
  try {
    const response = await request(url)
    if (!response.ok) {
      let detail = `下载失败（接口返回 ${response.status}）`
      try {
        const body = (await response.json()) as { detail?: string }
        if (body.detail) {
          detail = body.detail
        }
      } catch {
        // 保留默认提示
      }
      throw new Error(detail)
    }
    const blob = await response.blob()
    const match = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get('Content-Disposition') ?? '')
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = match ? decodeURIComponent(match[1]) : fallbackName
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下载失败'
  }
}

function downloadCurrent(row: Row) {
  void downloadZip(`${ENDPOINT}/${row.id}/versions/${row.当前版本}/download`, `${row.单证编号}-当前版.zip`)
}

function downloadVersion(version: number) {
  if (!activeDetail.value) {
    return
  }
  const detail = activeDetail.value
  void downloadZip(`${ENDPOINT}/${detail.id}/versions/${version}/download`, `${detail.单证编号}-v${version}.zip`)
}

function packageVoyage() {
  const voyage = packageVoyageNo.value.trim()
  if (!voyage) {
    errorMessage.value = '请先填航次编号再打包'
    return
  }
  void downloadZip(`${ENDPOINT}/package?voyage=${encodeURIComponent(voyage)}`, `${voyage}-单证材料包.zip`)
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) {
    query.set('keyword', filters.value.keyword)
  }
  if (filters.value.voyage) {
    query.set('voyage', filters.value.voyage)
  }
  if (filters.value.status) {
    query.set('status', filters.value.status)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('归档列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归档列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/export`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as { items?: Row[] }
    const items = payload.items ?? []
    stats.value = [
      { label: '待审核材料', value: items.filter((row) => row.status === '待审核').length },
      { label: '已审核材料', value: items.filter((row) => row.status === '已审核').length },
      {
        label: '历史版本（仅查看）',
        value: items.reduce((sum, row) => sum + Math.max(Number(row.版本数 ?? 1) - 1, 0), 0),
      },
    ]
  } catch {
    // 统计读取失败不挡主流程
  }
}

onMounted(() => {
  submitItems.value = [blankItem()]
  void reload()
  void loadStats()
})
</script>
