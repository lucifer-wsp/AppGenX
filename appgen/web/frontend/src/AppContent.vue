<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { marked } from 'marked'
import {
  NLayout,
  NLayoutHeader,
  NLayoutSider,
  NLayoutContent,
  NSteps,
  NStep,
  NButton,
  NDrawer,
  NDrawerContent,
  NTabs,
  NTab,
  NSpin,
  NEmpty,
  useMessage,
} from 'naive-ui'
import { api } from './api/client'
import LeftPanel from './components/LeftPanel.vue'
import ScanDiscovery from './components/ScanDiscovery.vue'
import PipelineTrack from './components/PipelineTrack.vue'
import SettingsPage from './components/SettingsPage.vue'

const message = useMessage()

const activeStep = ref(1)
const view = ref('scan')
const collapsed = ref(false)
const leftRunsCollapsed = ref(false)
const scanDiscoveryRef = ref(null)

const runs = ref([])
const currentRunId = ref(null)
const runDetail = ref(null)
const stageProgress = ref([])
const currentStage = ref('scout')
const stagePayload = ref(null)
const reviewNotes = ref('')
const autoReview = ref(false)

const readerOpen = ref(false)
const activeDoc = ref(null)
const docContent = ref(null)
const docLoading = ref(false)

let runsTimer = null
let runTimer = null
let runEventSource = null
const resuming = ref(false)
/** 用户点击「恢复执行」后，直到 run 结束（failed/paused/completed）前保持 busy */
const resumeRequested = ref(false)
/** 已提示过产出的阶段，避免重复 toast */
const stageOutputSeen = ref({})
/** 切换 run 并完成快照前不弹 toast */
const stageToastsEnabled = ref(false)

const STAGE_LABELS = {
  scout: 'Scout 商机侦察',
  analyst: 'Analyst 需求分析',
  pm: 'PM 产品定义',
  designer: 'Designer 设计',
  dev_init: 'Dev 开发计划',
  dev_scaffold: 'Dev 工程脚手架',
  dev_code: 'Dev 代码生成',
  dev_verify: 'Dev 编译验证',
  qa: 'QA 测试计划',
  store: 'Store 上架文案',
}

const resumeBusy = computed(() => {
  if (resuming.value) return true
  if (resumeRequested.value && runDetail.value?.status === 'running') {
    // 后台任务已结束但 status 仍为 running（进程重启/异常）时勿无限 loading
    if (runDetail.value.pipeline_active === false) return false
    return true
  }
  return false
})

const showResume = computed(() => {
  if (!currentRunId.value || !runDetail.value) return false
  const status = runDetail.value.status
  if (status === 'completed') return false
  if (resumeBusy.value) return true
  if (status === 'failed' || status === 'paused') return true
  if (runDetail.value.resumable) return true
  return false
})

const runAutoReview = computed(() => !!runDetail.value?.metadata?.auto_review)

const currentStageRow = computed(() =>
  stageProgress.value.find((s) => s.stage === currentStage.value) || null
)

const readerTitle = computed(() => docContent.value?.label || activeDoc.value || '文档')
const readerTabs = computed(() => stagePayload.value?.documents || [])
const runLogs = computed(() => (runDetail.value?.logs || []).slice(-12))
const showPipelineView = computed(() => view.value === 'pipeline' && !!currentRunId.value)

const renderedDoc = computed(() => {
  if (!docContent.value) return { type: 'empty' }
  const { type, content } = docContent.value
  if (type === 'markdown') return { type: 'html', html: content?.__html || '' }
  if (type === 'html') return { type: 'html', html: content || '' }
  if (type === 'json') {
    const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2)
    return { type: 'pre', text }
  }
  return { type: 'pre', text: String(content ?? '') }
})

async function loadRuns() {
  try { runs.value = await api.listRuns() } catch { /* ignore */ }
}

function resetStageOutputSeen(progress) {
  const seen = {}
  for (const row of progress || []) {
    if (row.has_output) seen[row.stage] = true
  }
  if (runDetail.value?.status === 'completed') seen.__completed = true
  stageOutputSeen.value = seen
}

function notifyStageOutputs(progress, run) {
  if (!stageToastsEnabled.value || !progress?.length || !run) return
  const seen = { ...stageOutputSeen.value }
  let changed = false
  for (const row of progress) {
    if (row.has_output && !seen[row.stage]) {
      const label = row.label || STAGE_LABELS[row.stage] || row.stage
      message.success(`${label} 已生成`)
      seen[row.stage] = true
      changed = true
    }
  }
  if (changed) stageOutputSeen.value = seen

  if (run.status === 'completed' && !seen.__completed) {
    message.success('流水线已全部完成')
    seen.__completed = true
    stageOutputSeen.value = seen
  } else if (run.status === 'failed' && resumeRequested.value) {
    resumeRequested.value = false
    if (runTimer) {
      clearInterval(runTimer)
      runTimer = setInterval(refreshRun, 6000)
    }
  } else if (run.status === 'paused' && resumeRequested.value) {
    resumeRequested.value = false
  } else if (run.status === 'completed' && resumeRequested.value) {
    resumeRequested.value = false
  }
}

function stopRunStream() {
  if (runEventSource) {
    runEventSource.close()
    runEventSource = null
  }
}

function applyRunStreamPayload(data) {
  if (!runDetail.value || !data) return
  runDetail.value = {
    ...runDetail.value,
    logs: data.logs ?? runDetail.value.logs,
    status: data.status ?? runDetail.value.status,
    updated_at: data.updated_at ?? runDetail.value.updated_at,
    pipeline_active: data.pipeline_active ?? runDetail.value.pipeline_active,
    active_stage: data.active_stage ?? runDetail.value.active_stage,
  }
  if (resumeRequested.value && runDetail.value.status === 'running' && runDetail.value.pipeline_active === false) {
    resumeRequested.value = false
    message.warning(
      runDetail.value.resume_block_reason
        || '后台任务已停止，若长时间无日志可再次点击「恢复执行」',
    )
  }
}

function startRunStream(runId) {
  stopRunStream()
  if (!runId) return
  runEventSource = new EventSource(`/api/runs/${runId}/events`)
  runEventSource.onmessage = (ev) => {
    try {
      applyRunStreamPayload(JSON.parse(ev.data))
    } catch { /* ignore */ }
  }
  runEventSource.addEventListener('done', async () => {
    stopRunStream()
    await refreshRun()
    await loadRuns()
  })
  runEventSource.onerror = () => {
    stopRunStream()
  }
}

async function refreshRun() {
  if (!currentRunId.value) return
  try {
    const [run, progress] = await Promise.all([
      api.getRun(currentRunId.value),
      api.getProgress(currentRunId.value),
    ])
    notifyStageOutputs(progress, run)
    runDetail.value = run
    stageProgress.value = progress
    if (resumeRequested.value && run.status === 'running' && run.pipeline_active === false) {
      resumeRequested.value = false
      message.warning(
        run.resume_block_reason
          || '后台任务已停止，若长时间无日志可再次点击「恢复执行」',
      )
    }
    const pending = run.reviews?.slice().reverse().find((g) => g.status === 'pending')
    if (pending) {
      const row = progress.find((s) => s.stage === pending.stage)
      if (row?.has_output && pending.stage !== currentStage.value) {
        currentStage.value = pending.stage
      }
    }
    await loadStageDocuments()
  } catch { /* ignore */ }
}

async function loadStageDocuments() {
  if (!currentRunId.value || !currentStage.value) return
  try {
    stagePayload.value = await api.getStageDocuments(currentRunId.value, currentStage.value)
  } catch {
    stagePayload.value = null
  }
}

async function selectRun(id) {
  currentRunId.value = id
  activeStep.value = 3
  view.value = 'pipeline'
  collapsed.value = false
  readerOpen.value = false
  activeDoc.value = null
  docContent.value = null
  resumeRequested.value = false
  resuming.value = false
  stageToastsEnabled.value = false
  stageOutputSeen.value = {}
  await refreshRun()
  resetStageOutputSeen(stageProgress.value)
  stageToastsEnabled.value = true
  if (runDetail.value?.metadata?.auto_review != null) {
    autoReview.value = !!runDetail.value.metadata.auto_review
  }
  if (runTimer) clearInterval(runTimer)
  const pollMs = runDetail.value?.status === 'running' ? 6000 : 10000
  runTimer = setInterval(refreshRun, pollMs)
  if (runDetail.value?.status === 'running' || runDetail.value?.pipeline_active) {
    startRunStream(id)
  } else {
    stopRunStream()
  }
  await loadRuns()
}

async function selectStage(stage) {
  currentStage.value = stage
  activeDoc.value = null
  docContent.value = null
  readerOpen.value = false
  await loadStageDocuments()
}

async function openDoc(docName) {
  if (!currentRunId.value) return
  activeDoc.value = docName
  readerOpen.value = true
  docLoading.value = true
  try {
    const data = await api.getDocument(currentRunId.value, docName)
    if (data.type === 'markdown') {
      docContent.value = { ...data, content: { __html: marked.parse(data.content || '') } }
    } else {
      docContent.value = data
    }
  } catch (e) {
    docContent.value = { type: 'text', content: e.message || '无法加载', label: docName }
  } finally {
    docLoading.value = false
  }
}

async function openDocFromNode(stage, docName) {
  await selectStage(stage)
  await openDoc(docName)
}

async function submitReview(action) {
  if (!currentRunId.value) return
  const notes = reviewNotes.value
  if ((action === 'revise' || action === 'reject') && !notes.trim()) {
    message.warning('修订或拒绝时请填写反馈')
    return
  }
  try {
    await api.submitReview(currentRunId.value, currentStage.value, action, notes)
    reviewNotes.value = ''
    readerOpen.value = false
    await refreshRun()
    await loadRuns()
    message.success('Review 已提交')
  } catch (e) {
    message.error(e.message || '操作失败')
  }
}

const settingsChanged = ref(false)

async function loadAppSettings() {
  try {
    const data = await api.getSettings()
    autoReview.value = !!data.auto_review_default
  } catch { /* ignore */ }
}

function openSettings() {
  settingsChanged.value = false
  view.value = 'settings'
}

function onSettingsSaved(data) {
  autoReview.value = !!data.auto_review_default
  settingsChanged.value = true
}

async function onSettingsBack() {
  view.value = 'scan'
  if (settingsChanged.value) {
    settingsChanged.value = false
    try {
      await scanDiscoveryRef.value?.reloadScanConfig?.()
    } catch {
      /* ScanDiscovery 内已提示 */
    }
  }
}

async function resumeRun() {
  if (!currentRunId.value || resumeBusy.value) return
  resuming.value = true
  try {
    await api.resumeRun(currentRunId.value)
    resumeRequested.value = true
    message.info('已恢复执行，后台运行中…')
    await refreshRun()
    await loadRuns()
    if (runTimer) clearInterval(runTimer)
    runTimer = setInterval(refreshRun, 6000)
    startRunStream(currentRunId.value)
  } catch (e) {
    message.error(e.message || '恢复失败')
    resumeRequested.value = false
  } finally {
    resuming.value = false
  }
}

function closePipelineView() {
  if (runTimer) clearInterval(runTimer)
  runTimer = null
  stopRunStream()
  resumeRequested.value = false
  resuming.value = false
  stageToastsEnabled.value = false
  stageOutputSeen.value = {}
  currentRunId.value = null
  runDetail.value = null
  stageProgress.value = []
  stagePayload.value = null
  readerOpen.value = false
  activeDoc.value = null
  docContent.value = null
  reviewNotes.value = ''
  view.value = 'scan'
  const hasScanData = scanDiscoveryRef.value?.hasScanData?.() ?? false
  activeStep.value = hasScanData ? 2 : 1
  syncSiderCollapse()
}

function onFocusOpportunities() {
  leftRunsCollapsed.value = true
  collapsed.value = true
}

function onExpandAllPanels() {
  leftRunsCollapsed.value = false
  collapsed.value = false
  scanDiscoveryRef.value?.expandPanels?.()
}

function syncSiderCollapse() {
  if (view.value === 'scan' && leftRunsCollapsed.value && !currentRunId.value) {
    collapsed.value = true
  }
}

function onRunsCollapsedChange(val) {
  leftRunsCollapsed.value = val
  if (!val) {
    collapsed.value = false
    return
  }
  syncSiderCollapse()
}

function onSiderExpand() {
  collapsed.value = false
  if (!currentRunId.value && leftRunsCollapsed.value) {
    leftRunsCollapsed.value = false
  }
}

function goToScanStep(step) {
  if (step === 1 || step === 2) {
    if (view.value === 'pipeline') {
      if (runTimer) clearInterval(runTimer)
      runTimer = null
      view.value = 'scan'
    }
    activeStep.value = step
  } else if (step === 3 && currentRunId.value) {
    view.value = 'pipeline'
    activeStep.value = 3
  }
}

function onScanStarted() {
  activeStep.value = 1
  view.value = 'scan'
}

function onScanComplete(payload = {}) {
  if (payload.opportunities?.length) activeStep.value = 2
}

function onPick(runId) {
  activeStep.value = 3
  selectRun(runId)
}

onMounted(() => {
  loadRuns()
  loadAppSettings()
  runsTimer = setInterval(loadRuns, 10000)
})

onUnmounted(() => {
  if (runsTimer) clearInterval(runsTimer)
  if (runTimer) clearInterval(runTimer)
  stopRunStream()
})

watch(readerOpen, (open) => {
  if (!open) {
    activeDoc.value = null
    docContent.value = null
  }
})

watch([leftRunsCollapsed, currentRunId, view], syncSiderCollapse)
</script>

<template>
  <n-layout style="height: 100vh">
    <n-layout-header bordered class="app-header">
      <div class="header-left">
        <div class="brand">
          <div class="logo">AG</div>
          <div>
            <div class="brand-title">AppGen Agent</div>
            <div class="brand-sub">App Store 智能体流水线</div>
          </div>
        </div>
      </div>
      <n-steps :current="activeStep" size="small" class="app-steps" @update:current="goToScanStep">
        <n-step title="市场扫描" />
        <n-step title="选择机会" />
        <n-step title="流水线" />
      </n-steps>
      <div class="header-right">
        <n-button
          v-if="showPipelineView"
          size="small"
          quaternary
          @click="closePipelineView"
        >
          返回扫描
        </n-button>
        <n-button
          v-if="showResume"
          size="small"
          type="primary"
          :loading="resumeBusy"
          :disabled="resumeBusy"
          @click="resumeRun"
        >
          恢复执行
        </n-button>
        <n-button
          size="small"
          quaternary
          circle
          title="设置"
          aria-label="设置"
          @click="openSettings"
        >
          <svg class="header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </svg>
        </n-button>
      </div>
    </n-layout-header>

    <n-layout has-sider position="absolute" class="app-body">
      <n-layout-sider
        bordered
        collapse-mode="width"
        :collapsed-width="0"
        :width="272"
        :collapsed="collapsed"
        show-trigger="bar"
        :native-scrollbar="false"
        content-style="padding: 12px"
        @collapse="collapsed = true"
        @expand="onSiderExpand"
      >
        <LeftPanel
          :runs-collapsed="leftRunsCollapsed"
          :runs="runs"
          :current-run-id="currentRunId"
          :stage="currentStageRow"
          :stage-payload="stagePayload"
          :review-notes="reviewNotes"
          :logs="runLogs"
          :auto-review="runAutoReview || autoReview"
          @select-run="selectRun"
          @close-run="closePipelineView"
          @open-doc="openDoc"
          @update:review-notes="reviewNotes = $event"
          @review="submitReview"
          @update:runs-collapsed="onRunsCollapsedChange"
        />
      </n-layout-sider>

      <n-layout-content
        native-scrollbar
        content-style="padding: 16px 20px 32px; min-width: 0; box-sizing: border-box;"
        content-class="main-scroll-content"
      >
        <SettingsPage
          v-show="view === 'settings'"
          class="settings-pane"
          @back="onSettingsBack"
          @saved="onSettingsSaved"
        />
        <ScanDiscovery
          v-show="view === 'scan'"
          ref="scanDiscoveryRef"
          class="scan-pane"
          :auto-review="autoReview"
          @scan-started="onScanStarted"
          @scan-complete="onScanComplete"
          @pick="onPick"
          @focus-opportunities="onFocusOpportunities"
          @expand-panels="onExpandAllPanels"
        />
        <PipelineTrack
          v-show="showPipelineView"
          class="pipeline-pane"
          :stages="stageProgress"
          :current-stage="currentStage"
          :run-detail="runDetail"
          @select-stage="selectStage"
          @open-doc="openDocFromNode"
          @close="closePipelineView"
        />
        <n-empty
          v-if="view !== 'scan' && !showPipelineView"
          description="从左侧选择运行，或开始市场扫描"
          style="margin-top: 80px"
        />
      </n-layout-content>
    </n-layout>

    <n-drawer v-model:show="readerOpen" :width="480" placement="right">
      <n-drawer-content :title="readerTitle" closable>
        <n-tabs
          v-if="readerTabs.length"
          type="segment"
          size="small"
          :value="activeDoc"
          @update:value="openDoc"
        >
          <n-tab v-for="t in readerTabs" :key="t.name" :name="t.name" :tab="t.label" />
        </n-tabs>
        <n-spin :show="docLoading" style="margin-top: 12px">
          <n-empty v-if="!activeDoc" description="选择文档标签开始阅读" size="small" style="padding: 40px 0" />
          <div v-else-if="renderedDoc.type === 'html'" class="doc-prose" v-html="renderedDoc.html" />
          <pre v-else class="doc-pre">{{ renderedDoc.text }}</pre>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </n-layout>
</template>

<style scoped>
.app-header {
  height: 56px;
  padding: 0 20px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 16px;
}

.header-left {
  justify-self: start;
  min-width: 0;
}

.header-right {
  justify-self: end;
  min-width: 0;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
}

.auto-review-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.header-icon {
  width: 18px;
  height: 18px;
}

.settings-pane {
  min-width: 0;
}

.switch-label {
  font-size: 12px;
  opacity: 0.65;
  white-space: nowrap;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
}

.brand-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.2;
}

.brand-sub {
  font-size: 11px;
  opacity: 0.45;
  line-height: 1.2;
}

.app-steps {
  justify-self: center;
  width: max-content;
  max-width: min(420px, calc(100vw - 280px));
}

.app-steps :deep(.n-steps) {
  justify-content: center;
}

.app-body {
  top: 56px;
  bottom: 0;
  left: 0;
  right: 0;
}

:deep(.main-scroll-content) {
  overflow-y: auto;
  overflow-x: hidden;
  height: 100%;
  box-sizing: border-box;
}

.scan-pane,
.pipeline-pane {
  min-width: 0;
}

.pipeline-pane {
  min-height: 100%;
}

@media (max-width: 768px) {
  .app-steps {
    display: none;
  }
}
</style>
