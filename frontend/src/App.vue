<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">港口集装箱作业调度平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向船舶靠泊、集装箱装卸、堆场堆存、闸口进出与理货结算的一体化港口作业调度后台。</span>
        <span class="head-user">当前值班：{{ store.operator }} · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "泊位计划", path: "/berth" }, { label: "船舶档案", path: "/vessel" }, { label: "航次管理", path: "/voyage" }, { label: "岸桥作业", path: "/crane" }, { label: "装卸任务", path: "/loading" }, { label: "堆场管理", path: "/yard" }, { label: "集装箱档案", path: "/container" }, { label: "堆存记录", path: "/yardstore" }, { label: "闸口通行", path: "/gate" }, { label: "集卡调度", path: "/truck" }, { label: "理货作业", path: "/tally" }, { label: "残损登记", path: "/damage" }, { label: "单证处理", path: "/manifest" }, { label: "单证材料归档", path: "/docarchive" }, { label: "堆存计费", path: "/storage" }, { label: "引航拖轮", path: "/pilot" }, { label: "安全监督", path: "/safety" }, { label: "货主档案", path: "/customer" }, { label: "作业结算", path: "/settle" }]
</script>
