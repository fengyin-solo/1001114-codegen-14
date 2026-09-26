import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Berth = () => import('@/views/berth/index.vue')
const Vessel = () => import('@/views/vessel/index.vue')
const Voyage = () => import('@/views/voyage/index.vue')
const Crane = () => import('@/views/crane/index.vue')
const Loading = () => import('@/views/loading/index.vue')
const Yard = () => import('@/views/yard/index.vue')
const Container = () => import('@/views/container/index.vue')
const Yardstore = () => import('@/views/yardstore/index.vue')
const Gate = () => import('@/views/gate/index.vue')
const Truck = () => import('@/views/truck/index.vue')
const Tally = () => import('@/views/tally/index.vue')
const Damage = () => import('@/views/damage/index.vue')
const Manifest = () => import('@/views/manifest/index.vue')
const Docarchive = () => import('@/views/docarchive/index.vue')
const Storage = () => import('@/views/storage/index.vue')
const Pilot = () => import('@/views/pilot/index.vue')
const Safety = () => import('@/views/safety/index.vue')
const Customer = () => import('@/views/customer/index.vue')
const Settle = () => import('@/views/settle/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/berth', name: 'berth', component: Berth },
    { path: '/vessel', name: 'vessel', component: Vessel },
    { path: '/voyage', name: 'voyage', component: Voyage },
    { path: '/crane', name: 'crane', component: Crane },
    { path: '/loading', name: 'loading', component: Loading },
    { path: '/yard', name: 'yard', component: Yard },
    { path: '/container', name: 'container', component: Container },
    { path: '/yardstore', name: 'yardstore', component: Yardstore },
    { path: '/gate', name: 'gate', component: Gate },
    { path: '/truck', name: 'truck', component: Truck },
    { path: '/tally', name: 'tally', component: Tally },
    { path: '/damage', name: 'damage', component: Damage },
    { path: '/manifest', name: 'manifest', component: Manifest },
    { path: '/docarchive', name: 'docarchive', component: Docarchive },
    { path: '/storage', name: 'storage', component: Storage },
    { path: '/pilot', name: 'pilot', component: Pilot },
    { path: '/safety', name: 'safety', component: Safety },
    { path: '/customer', name: 'customer', component: Customer },
    { path: '/settle', name: 'settle', component: Settle },
  ],
})

export default router
