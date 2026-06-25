<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NCard,
  NGrid,
  NGi,
  NFormItem,
  NInput,
  NInputNumber,
  NCheckbox,
  NCheckboxGroup,
  NButton,
  NSpace,
  NAlert,
  NTag,
  NEmpty,
  NScrollbar,
  NSpin,
  NDivider,
  NModal,
  useMessage,
  useDialog,
} from 'naive-ui'
import { api } from '../api/client'
import CollapsiblePanel from './CollapsiblePanel.vue'
import AdaptiveSelect from './AdaptiveSelect.vue'

const props = defineProps({
  autoReview: { type: Boolean, default: false },
})

const emit = defineEmits(['scan-started', 'scan-complete', 'pick', 'focus-opportunities', 'expand-panels'])
const message = useMessage()
const dialog = useDialog()

const keyword = ref('')
const genreIds = ref([])
const regions = ref([])
const chartTypes = ref(['top-free', 'top-paid'])
const limit = ref(10)
const limitMin = ref(1)
const limitMax = ref(100)
const defaultEnrich = ref(5)

const genres = ref([])
const popularIds = ref([])
const regionOptions = ref([])
const estimate = ref(null)
const estimateError = ref('')

const scanning = ref(false)
const analyzing = ref(false)
const scanId = ref(null)
const scanStatus = ref('')
const scanLogs = ref([])
const opportunities = ref([])
const categoryCount = ref(0)
const analysisProgress = ref({ done: 0, total: 0 })
const scanTerminalStatus = ref('')

const recentScans = ref([])
const selectedRecentScanId = ref(null)

const preferenceStats = ref({ bad: 0, good: 0 })
const hideRejected = ref(true)
const showFeedbackModal = ref(false)
const feedbackReason = ref('')
const pendingFeedback = ref(null)

const configCollapsed = ref(false)
const statusCollapsed = ref(false)

const STATUS_PANEL_HEIGHT_KEY = 'appgen_status_panel_height'
const STATUS_PANEL_MIN_HEIGHT = 168
const statusPanelHeight = ref(0)
const configPanelRef = ref(null)
const statusPanelShellRef = ref(null)
const logScrollRef = ref(null)
const scanTopMaxHeight = ref(480)
const statusResizing = ref(false)
let configResizeObserver = null

const focusOpportunitiesMode = computed(
  () => configCollapsed.value && statusCollapsed.value && showOpportunitiesCard.value
)

const statusSummary = computed(() => {
  if (isScanActive.value) return scanStatus.value || '扫描进行中…'
  if (scanTerminalStatus.value === 'failed' && categoryCount.value > 0) {
    return `分析失败 · ${categoryCount.value} 个快照可重试`
  }
  if (opportunities.value.length) return `${opportunities.value.length} 条机会`
  return scanStatus.value || '等待扫描'
})

const REGION_PRESET_LABELS = {
  'us-eu': '美区 + 欧洲',
  us: '仅美国',
  eu: '仅欧洲',
}

function buildRegionOptions(presets) {
  return Object.keys(presets || {})
    .filter((key) => key?.trim())
    .map((key) => ({
      label: REGION_PRESET_LABELS[key] || key,
      value: key,
    }))
}

function presetKeySet() {
  return new Set(regionOptions.value.map((o) => o.value))
}

function resolveRegionSelection(candidates, settingsData) {
  const keys = presetKeySet()
  let selected = []
  if (Array.isArray(candidates)) {
    selected = candidates.filter((k) => keys.has(k))
  } else if (typeof candidates === 'string' && candidates.trim()) {
    selected = candidates
      .split(',')
      .map((s) => s.trim())
      .filter((k) => keys.has(k))
  }
  if (selected.length) return selected

  const def = settingsData.default_region_preset
  if (def) {
    const fromDef = String(def)
      .split(',')
      .map((s) => s.trim())
      .filter((k) => keys.has(k))
    if (fromDef.length) return fromDef
  }
  return regionOptions.value[0] ? [regionOptions.value[0].value] : []
}

function applyScanDefaults(settingsData) {
  regions.value = resolveRegionSelection(settingsData.default_region_preset, settingsData)
  if (settingsData.default_scan_limit != null) {
    limit.value = settingsData.default_scan_limit
  }
  if (settingsData.default_charts?.length) {
    chartTypes.value = [...settingsData.default_charts]
  }
  if (settingsData.default_scan_enrich != null) {
    defaultEnrich.value = settingsData.default_scan_enrich
  }
  if (settingsData.scan_limit_min != null) {
    limitMin.value = settingsData.scan_limit_min
  }
  if (settingsData.scan_limit_max != null) {
    limitMax.value = settingsData.scan_limit_max
  }
  genreIds.value = [...popularIds.value]
}

function reconcileScanSelections(settingsData) {
  regions.value = resolveRegionSelection(regions.value, settingsData)
  const validGenreIds = new Set(genres.value.map((g) => g.id))
  genreIds.value = genreIds.value.filter((id) => validGenreIds.has(id))
  if (!genreIds.value.length && popularIds.value.length) {
    genreIds.value = [...popularIds.value]
  }
}

async function loadScanConfig({ applyDefaults = false } = {}) {
  try {
    const [genreData, settingsData] = await Promise.all([api.listGenres(), api.getSettings()])
    genres.value = genreData.genres || []
    popularIds.value = genreData.popular_ids || []
    regionOptions.value = buildRegionOptions(settingsData.region_presets)

    if (applyDefaults) {
      applyScanDefaults(settingsData)
    } else {
      reconcileScanSelections(settingsData)
    }
    await updateEstimate()
    await loadRecentScans()
  } catch {
    estimateError.value = '无法连接后端，请先运行 appgen serve（默认端口 8787）'
    throw new Error(estimateError.value)
  }
}

async function reloadScanConfig() {
  try {
    await loadScanConfig({ applyDefaults: true })
    message.success('扫描配置已同步最新设置')
  } catch (e) {
    message.error(e.message || '同步扫描配置失败')
  }
}

const chartOptions = [
  { label: '免费榜', value: 'top-free' },
  { label: '付费榜', value: 'top-paid' },
  { label: '畅销榜', value: 'top-grossing' },
]

const genreOptions = computed(() =>
  genres.value.map((g) => ({ label: g.name_zh, value: g.id }))
)

const scanBody = computed(() => ({
  keyword: keyword.value.trim() || null,
  genre_ids: genreIds.value,
  regions: regions.value.length ? regions.value.join(',') : '',
  charts: chartTypes.value.length ? chartTypes.value : ['top-free'],
}))

const stopping = ref(false)

const isScanActive = computed(() => scanning.value || analyzing.value)

const showStopScan = computed(
  () => !!scanId.value && isScanActive.value && scanTerminalStatus.value !== 'cancelled'
)

const showStopAnalysis = computed(() => analyzing.value)

const canReanalyze = computed(
  () => !!scanId.value && categoryCount.value > 0 && !isScanActive.value
)

const reanalyzableScans = computed(() =>
  recentScans.value.filter(
    (s) => (s.category_count ?? 0) > 0 && s.status !== 'legacy_unsupported'
  )
)

const SCAN_STATUS_LABELS = {
  completed: '完成',
  failed: '失败',
  cancelled: '已停止',
  running: '进行中',
  legacy_unsupported: '不支持',
}

function formatScanDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const recentScanOptions = computed(() =>
  reanalyzableScans.value.map((s) => {
    const keyword = (s.focus_keyword || '').trim()
    const status = SCAN_STATUS_LABELS[s.status] || s.status
    const snapshots = s.category_count ?? 0
    const opportunities = s.opportunity_count ?? 0
    return {
      label: keyword ? `${keyword} · ${s.id}` : s.id,
      value: s.id,
      keyword: keyword || undefined,
      statusLabel: status,
      statusCompleted: s.status === 'completed',
      statusLine: `${snapshots} 快照 · ${opportunities} 机会`,
      dateLine: formatScanDate(s.updated_at),
      searchText: [keyword, s.id].filter(Boolean).join(' ').toLowerCase(),
    }
  })
)

const showOpportunitiesCard = computed(
  () =>
    analyzing.value ||
    opportunities.value.length > 0 ||
    (canReanalyze.value && ['failed', 'cancelled'].includes(scanTerminalStatus.value))
)

const opportunitiesLoading = computed(
  () => analyzing.value && opportunities.value.length === 0
)

const visibleOpportunities = computed(() => {
  if (!hideRejected.value) return opportunities.value
  return opportunities.value.filter((o) => o.feedback?.verdict !== 'bad')
})

const rejectedInScanCount = computed(
  () => opportunities.value.filter((o) => o.feedback?.verdict === 'bad').length
)

function inferPhase(scan) {
  if (scan.phase === 'analyze' || scan.phase === 'done') return scan.phase
  if (scan.status === 'running' && (scan.category_count ?? 0) > 0) return 'analyze'
  if ((scan.analysis_batches_total ?? 0) > 0) return 'analyze'
  return scan.phase || 'fetch'
}

function formatStatus(scan) {
  const count = scan.category_count ?? 0
  const oppCount = scan.opportunities?.length ?? 0
  const phase = inferPhase(scan)
  const done = scan.analysis_batches_done ?? 0
  const total = scan.analysis_batches_total ?? 0

  if (scan.status === 'failed') {
    return `失败: ${scan.error || '网络异常，请检查代理或稍后重试'}`
  }

  if (scan.status === 'cancelled') {
    const count = scan.category_count ?? 0
    const oppCount = scan.opportunities?.length ?? 0
    return `已停止 · ${count} 个快照${oppCount ? ` · ${oppCount} 条机会` : ''}`
  }

  if (phase === 'analyze') {
    if (total > 0) {
      return `榜单已采集（${count} 个快照）· LLM 分析中 ${done}/${total} 批 · 已发现 ${oppCount} 条机会`
    }
    return `榜单已采集（${count} 个快照）· LLM 正在分析机会，请稍候…`
  }

  if (scan.status === 'running') {
    return '正在拉取 App Store 榜单数据…'
  }

  if (scan.status === 'completed') {
    return `完成 · ${count} 个榜单快照 · ${oppCount} 条机会`
  }

  return scanStatus.value || '配置参数后点击开始扫描'
}

async function loadRecentScans() {
  try {
    recentScans.value = await api.listScans()
    if (!scanId.value && reanalyzableScans.value.length) {
      selectedRecentScanId.value = reanalyzableScans.value[0].id
    }
  } catch {
    recentScans.value = []
  }
}

async function loadRecentScan() {
  if (!selectedRecentScanId.value) return
  stopPolling()
  scanId.value = selectedRecentScanId.value
  scanning.value = false
  analyzing.value = false
  opportunities.value = []
  scanLogs.value = []
  scanTerminalStatus.value = ''
  await pollScan()
}

async function updateEstimate() {
  estimateError.value = ''
  try {
    estimate.value = await api.estimateScan(scanBody.value)
  } catch (e) {
    estimate.value = null
    estimateError.value = e.message || '无法估算'
  }
}

function selectPopular() {
  genreIds.value = [...popularIds.value]
  updateEstimate()
}

function selectAll() {
  genreIds.value = genres.value.map((g) => g.id)
  updateEstimate()
}

function clearGenres() {
  genreIds.value = []
  updateEstimate()
}

async function startScan() {
  const kw = keyword.value.trim()
  if (!kw && !genreIds.value.length) {
    dialog.warning({
      title: '全品类扫描',
      content: '未选品类将执行全品类扫描，可能需 15–40 分钟。确定继续？',
      positiveText: '继续',
      negativeText: '取消',
      onPositiveClick: () => { doStartScan(); return true },
    })
    return
  }
  await doStartScan()
}

async function doStartScan() {
  if (!regions.value.length) {
    message.warning('请至少选择一个区域')
    return
  }
  scanning.value = true
  analyzing.value = false
  scanStatus.value = '正在启动…'
  opportunities.value = []
  scanTerminalStatus.value = ''
  scanLogs.value = []
  analysisProgress.value = { done: 0, total: 0 }

  try {
    const data = await api.createScan({
      ...scanBody.value,
      limit: limit.value,
      enrich: defaultEnrich.value,
    })
    scanId.value = data.id
    persistScanId(data.id)
    selectedRecentScanId.value = data.id
    scanStatus.value = `扫描中 · ${data.plan?.description || ''}`
    emit('scan-started')
    startPolling()
  } catch (e) {
    scanning.value = false
    message.error(e.message || '启动失败')
  }
}

function applyScanState(scan) {
  const prevLogCount = scanLogs.value.length
  scanLogs.value = scan.logs || []
  categoryCount.value = scan.category_count ?? 0
  scanTerminalStatus.value = scan.status || ''
  if (scan.preference_stats) {
    preferenceStats.value = scan.preference_stats
  }
  analysisProgress.value = {
    done: scan.analysis_batches_done ?? 0,
    total: scan.analysis_batches_total ?? 0,
  }

  const phase = inferPhase(scan)
  analyzing.value = scan.status === 'running' && phase === 'analyze'
  scanning.value = scan.status === 'running' && phase === 'fetch'

  if (scan.opportunities?.length) {
    opportunities.value = scan.opportunities
  }
  if (scanId.value) persistScanId(scanId.value)

  scanStatus.value = formatStatus(scan)

  if (scanLogs.value.length > prevLogCount) {
    nextTick(() => {
      const el = logScrollRef.value?.$el?.querySelector?.('.n-scrollbar-container')
      if (el) el.scrollTop = el.scrollHeight
    })
  }
}

function openFeedbackModal(opp, verdict) {
  pendingFeedback.value = { opp, verdict }
  feedbackReason.value = opp.feedback?.reason || ''
  if (verdict === 'good') {
    submitFeedback('', false)
    return
  }
  showFeedbackModal.value = true
}

async function submitFeedback(reasonOverride, fromModal = true) {
  if (!scanId.value || !pendingFeedback.value) return
  const { opp, verdict } = pendingFeedback.value
  const reason = fromModal ? (reasonOverride ?? feedbackReason.value) : reasonOverride
  try {
    const data = await api.submitOpportunityFeedback(scanId.value, {
      rank: opp.rank,
      verdict,
      reason: reason.trim(),
    })
    preferenceStats.value = data.preference_stats || preferenceStats.value
    opportunities.value = opportunities.value.map((item) =>
      item.rank === opp.rank
        ? {
            ...item,
            feedback: {
              id: data.id,
              verdict: data.verdict,
              reason: reason.trim(),
            },
          }
        : item
    )
    message.success(verdict === 'bad' ? '已记录，后续扫描/分析将避开类似方向' : '已记录偏好')
    showFeedbackModal.value = false
    pendingFeedback.value = null
    feedbackReason.value = ''
    return true
  } catch (e) {
    message.error(e.message || '反馈失败')
    return false
  }
}

async function clearFeedback(opp) {
  if (!opp.feedback?.id) return
  try {
    await api.deleteScanPreference(opp.feedback.id)
    opportunities.value = opportunities.value.map((item) =>
      item.rank === opp.rank ? { ...item, feedback: undefined } : item
    )
    const prefs = await api.getScanPreferences()
    preferenceStats.value = { bad: prefs.bad_count, good: prefs.good_count }
    message.success('已撤销反馈')
  } catch (e) {
    message.error(e.message || '撤销失败')
  }
}

async function pollScan() {
  if (!scanId.value) return
  try {
    const scan = await api.getScan(scanId.value)
    applyScanState(scan)

    if (scan.status === 'running') return

    stopPolling()
    scanning.value = false
    analyzing.value = false
    stopping.value = false

    if (scan.status === 'cancelled') {
      await loadRecentScans()
      emit('scan-complete', { cancelled: true })
      return
    }

    if (scan.status === 'failed') {
      await loadRecentScans()
      emit('scan-complete', { failed: true })
      return
    }

    if (!scan.opportunities?.length && categoryCount.value > 0) {
      opportunities.value = []
      await loadRecentScans()
      emit('scan-complete', { opportunities: [] })
      return
    }

    opportunities.value = scan.opportunities || []
    await loadRecentScans()
    emit('scan-complete', { opportunities: opportunities.value })
  } catch { /* ignore */ }
}

async function stopScan() {
  if (!scanId.value || stopping.value) return
  stopping.value = true
  try {
    await api.cancelScan(scanId.value)
    message.info('正在停止扫描…')
    await pollScan()
  } catch (e) {
    stopping.value = false
    message.error(e.message || '停止失败')
  }
}

async function reanalyzeFromPicker() {
  if (!selectedRecentScanId.value) {
    message.warning('请先选择最近扫描')
    return
  }
  if (scanId.value !== selectedRecentScanId.value) {
    await loadRecentScan()
  }
  if (!categoryCount.value) {
    message.error('该扫描无榜单数据，请重新扫描')
    return
  }
  await reanalyze()
}

async function reanalyze() {
  if (!scanId.value) return
  scanning.value = false
  analyzing.value = true
  opportunities.value = []
  scanTerminalStatus.value = 'running'
  scanStatus.value = '榜单数据就绪，正在重新分析机会…'
  startPolling()
  try {
    await api.reanalyzeScan(scanId.value)
  } catch (e) {
    analyzing.value = false
    scanTerminalStatus.value = 'failed'
    message.error(e.message || '分析失败')
  }
}

async function pick(rank) {
  if (!scanId.value) return
  try {
    const data = await api.pickOpportunity(scanId.value, rank, { autoReview: props.autoReview })
    message.success('已启动流水线')
    emit('pick', data.run_id)
  } catch (e) {
    message.error(e.message || '失败')
  }
}

let pollTimer = null

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollScan, 800)
  pollScan()
}

function persistScanId(id) {
  if (id) sessionStorage.setItem('appgen_last_scan_id', id)
}

function focusOpportunities() {
  configCollapsed.value = true
  statusCollapsed.value = true
  emit('focus-opportunities')
}

function expandPanels() {
  configCollapsed.value = false
  statusCollapsed.value = false
  emit('expand-panels')
}

function syncScanTopMaxHeight() {
  const el = configPanelRef.value
  if (!el) return
  const next = el.offsetHeight
  if (next > 0) scanTopMaxHeight.value = next
  if (statusPanelHeight.value > scanTopMaxHeight.value) {
    statusPanelHeight.value = scanTopMaxHeight.value
  }
}

const statusShellStyle = computed(() => {
  if (statusCollapsed.value) return undefined
  const height = statusPanelHeight.value
  if (!height) return undefined
  return { height: `${Math.min(Math.max(height, STATUS_PANEL_MIN_HEIGHT), scanTopMaxHeight.value)}px` }
})

function startStatusResize(event) {
  if (statusCollapsed.value) return
  event.preventDefault()
  const shell = statusPanelShellRef.value
  const startY = event.clientY
  const startHeight = shell?.offsetHeight || STATUS_PANEL_MIN_HEIGHT
  statusResizing.value = true
  document.body.classList.add('status-panel-resizing')

  const onMove = (ev) => {
    syncScanTopMaxHeight()
    const delta = ev.clientY - startY
    const next = Math.min(
      scanTopMaxHeight.value,
      Math.max(STATUS_PANEL_MIN_HEIGHT, startHeight + delta)
    )
    statusPanelHeight.value = next
  }

  const onUp = () => {
    statusResizing.value = false
    document.body.classList.remove('status-panel-resizing')
    if (statusPanelHeight.value) {
      sessionStorage.setItem(STATUS_PANEL_HEIGHT_KEY, String(statusPanelHeight.value))
    }
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function setupConfigHeightObserver() {
  if (!configPanelRef.value || typeof ResizeObserver === 'undefined') return
  configResizeObserver = new ResizeObserver(() => syncScanTopMaxHeight())
  configResizeObserver.observe(configPanelRef.value)
}

watch(configCollapsed, () => {
  nextTick(() => syncScanTopMaxHeight())
})

function hasScanData() {
  return (
    opportunities.value.length > 0
    || !!scanId.value
    || isScanActive.value
    || categoryCount.value > 0
  )
}

defineExpose({ hasScanData, expandPanels, reloadScanConfig })

async function initScanDiscovery() {
  try {
    await loadScanConfig({ applyDefaults: true })
  } catch {
    /* loadScanConfig 已设置 estimateError */
  }
  const savedHeight = Number(sessionStorage.getItem(STATUS_PANEL_HEIGHT_KEY))
  if (savedHeight >= STATUS_PANEL_MIN_HEIGHT) {
    statusPanelHeight.value = savedHeight
  }
  const lastId = sessionStorage.getItem('appgen_last_scan_id')
  if (lastId && !scanId.value) {
    scanId.value = lastId
    selectedRecentScanId.value = lastId
    await pollScan()
  }
  await nextTick()
  syncScanTopMaxHeight()
  setupConfigHeightObserver()
}

onMounted(initScanDiscovery)
onUnmounted(() => {
  stopPolling()
  configResizeObserver?.disconnect()
})
</script>

<template>
  <div class="scan-page" :class="{ 'focus-opportunities': focusOpportunitiesMode }">
    <n-space v-if="showOpportunitiesCard" justify="space-between" align="center" class="focus-toolbar">
      <span class="focus-summary">
        {{ visibleOpportunities.length }} 条机会
        <template v-if="scanId"> · 扫描 {{ scanId }}</template>
      </span>
      <n-space :size="8">
        <n-button
          v-if="!focusOpportunitiesMode"
          size="small"
          type="primary"
          secondary
          @click="focusOpportunities"
        >
          专注查看机会
        </n-button>
        <n-button v-else size="small" quaternary @click="expandPanels">
          展开配置与状态
        </n-button>
      </n-space>
    </n-space>

    <n-grid
      :x-gap="16"
      :y-gap="16"
      cols="1 m:2"
      responsive="screen"
      class="scan-top-grid"
    >
      <n-gi>
        <div ref="configPanelRef" class="scan-panel-anchor">
        <CollapsiblePanel v-model:collapsed="configCollapsed" title="市场扫描配置">
          <n-space vertical :size="14">
            <n-form-item label="关键词（可选）" :show-feedback="false">
              <n-input
                v-model:value="keyword"
                placeholder="如 habit tracker、focus timer"
                clearable
                @update:value="updateEstimate"
              />
            </n-form-item>

            <n-form-item label="品类" :show-feedback="false">
              <n-space :size="8" style="margin-bottom: 8px">
                <n-button size="tiny" @click="selectPopular">热门 7 类</n-button>
                <n-button size="tiny" @click="selectAll">全选</n-button>
                <n-button size="tiny" quaternary @click="clearGenres">清空</n-button>
              </n-space>
              <AdaptiveSelect
                v-model:value="genreIds"
                :options="genreOptions"
                multiple
                filterable
                placeholder="选择品类"
                modal-title="选择品类"
                max-tag-count="responsive"
                @update:value="updateEstimate"
              />
            </n-form-item>

            <n-grid :x-gap="12" cols="2">
              <n-gi>
                <n-form-item label="区域" :show-feedback="false">
                  <AdaptiveSelect
                    v-model:value="regions"
                    :options="regionOptions"
                    multiple
                    filterable
                    placeholder="选择区域"
                    modal-title="选择区域"
                    max-tag-count="responsive"
                    @update:value="updateEstimate"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="每类条数" :show-feedback="false">
                  <n-input-number
                    v-model:value="limit"
                    :min="limitMin"
                    :max="limitMax"
                    style="width: 100%"
                  />
                </n-form-item>
              </n-gi>
            </n-grid>

            <n-form-item label="榜单类型" :show-feedback="false">
              <n-checkbox-group v-model:value="chartTypes" @update:value="updateEstimate">
                <n-space>
                  <n-checkbox v-for="o in chartOptions" :key="o.value" :value="o.value" :label="o.label" />
                </n-space>
              </n-checkbox-group>
            </n-form-item>

            <n-alert v-if="estimate" type="info" :bordered="false" size="small">
              <div>{{ estimate.description }}</div>
              <div style="font-size: 12px; opacity: 0.65; margin-top: 4px">
                {{ estimate.requests }} 请求 · {{ estimate.countries }} 区域 · ~{{ estimate.estimate_minutes }} 分钟
              </div>
            </n-alert>
            <n-alert v-else-if="estimateError" type="error" :bordered="false" size="small">
              {{ estimateError }}
            </n-alert>

            <n-button type="primary" block :loading="scanning" :disabled="analyzing" @click="startScan">
              {{ scanning ? '拉取榜单中…' : '开始扫描（拉取榜单 + 分析）' }}
            </n-button>

            <template v-if="recentScanOptions.length">
              <n-divider style="margin: 4px 0">或复用已有榜单</n-divider>
              <n-form-item label="最近扫描" :show-feedback="false">
                <AdaptiveSelect
                  v-model:value="selectedRecentScanId"
                  :options="recentScanOptions"
                  placeholder="选择已有扫描"
                  modal-title="选择已有扫描"
                  search-placeholder="按名称或 ID 搜索…"
                  rich-options
                  clearable
                />
              </n-form-item>
              <n-space :size="8">
                <n-button block :disabled="!selectedRecentScanId || isScanActive" @click="loadRecentScan">
                  加载扫描
                </n-button>
                <n-button
                  block
                  type="warning"
                  :disabled="!selectedRecentScanId || isScanActive"
                  :loading="analyzing"
                  @click="reanalyzeFromPicker"
                >
                  仅重新分析
                </n-button>
              </n-space>
            </template>
          </n-space>
        </CollapsiblePanel>
        </div>
      </n-gi>

      <n-gi>
        <div
          ref="statusPanelShellRef"
          class="status-panel-shell"
          :class="{ resizing: statusResizing, collapsed: statusCollapsed }"
          :style="statusShellStyle"
        >
        <CollapsiblePanel
          v-model:collapsed="statusCollapsed"
          title="扫描状态"
          fill
          class="status-panel-inner"
        >
          <template #header-extra>
            <n-space align="center" :size="8">
              <n-button
                v-if="showStopScan"
                size="tiny"
                quaternary
                circle
                type="error"
                title="停止扫描"
                aria-label="停止扫描"
                :loading="stopping"
                @click="stopScan"
              >
                <svg class="stop-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
                </svg>
              </n-button>
              <n-spin v-if="isScanActive" size="small" />
              <span v-if="statusCollapsed && statusSummary" class="status-summary">{{ statusSummary }}</span>
            </n-space>
          </template>
          <div class="status-body">
          <div class="status-main">
          <n-alert
            v-if="scanTerminalStatus === 'failed' && categoryCount > 0"
            type="error"
            :bordered="false"
            size="small"
            style="margin-bottom: 10px"
          >
            榜单已采集（{{ categoryCount }} 个快照），但 LLM 分析失败。修复 LLM 配置后可直接重新分析，无需重扫。
          </n-alert>
          <n-alert
            v-else-if="analyzing"
            type="warning"
            :bordered="false"
            size="small"
            style="margin-bottom: 10px"
          >
            榜单数据已就绪，正在调用 LLM 分析机会（通常需 20–60 秒），结果会陆续出现。
          </n-alert>
          <div class="status-text">
            {{ scanStatus || '配置参数后点击开始扫描' }}
          </div>
          <n-space v-if="canReanalyze" :size="8" style="margin-top: 12px">
            <n-button type="primary" size="small" :loading="analyzing" @click="reanalyze">
              重新分析机会
            </n-button>
            <span class="reanalyze-hint">复用 {{ categoryCount }} 个榜单快照，无需重新拉取</span>
          </n-space>
          </div>
          <template v-if="scanLogs.length">
            <div class="section-label status-log-label">实时日志</div>
            <n-scrollbar ref="logScrollRef" class="status-log-scroll">
              <pre class="log-pre">{{ scanLogs.slice(-80).join('\n') }}</pre>
            </n-scrollbar>
          </template>
          </div>
        </CollapsiblePanel>
        <div
          v-if="!statusCollapsed"
          class="status-resize-handle"
          title="拖动调整日志区域高度"
          @mousedown="startStatusResize"
        >
          <span class="resize-grip" aria-hidden="true" />
        </div>
        </div>
      </n-gi>
    </n-grid>

    <n-card
      v-if="showOpportunitiesCard"
      size="small"
      class="opp-card opp-section"
      :class="{ expanded: focusOpportunitiesMode }"
    >
      <template #header>
        <div class="card-head">
          <span>发现的机会</span>
          <n-space align="center" :size="8">
            <n-button
              v-if="showStopAnalysis"
              size="tiny"
              quaternary
              circle
              type="error"
              title="停止分析"
              aria-label="停止分析"
              :loading="stopping"
              @click="stopScan"
            >
              <svg class="stop-icon" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
              </svg>
            </n-button>
            <n-tag v-if="preferenceStats.bad" size="small" type="error" :bordered="false">
              已排除 {{ preferenceStats.bad }} 类
            </n-tag>
            <n-spin v-if="isScanActive" size="small" />
          </n-space>
        </div>
      </template>

      <n-alert
        v-if="preferenceStats.bad || preferenceStats.good"
        type="info"
        :bordered="false"
        size="small"
        style="margin-bottom: 12px"
      >
        你的反馈会写入偏好库，下次扫描/重新分析时 LLM 将避开「不符合」的方向，并优先参考「符合」的方向。
      </n-alert>

      <n-spin :show="opportunitiesLoading">
        <n-empty
          v-if="!opportunities.length && !analyzing && canReanalyze"
          description="暂无机会，点击「重新分析机会」重试"
          size="small"
        />
        <n-empty
          v-else-if="!opportunities.length && !analyzing"
          description="暂无机会"
          size="small"
        />
        <template v-else-if="!opportunities.length && analyzing">
          <div class="analyzing-hint">LLM 正在分析第一批机会…</div>
        </template>
        <template v-else>
          <n-space v-if="rejectedInScanCount" justify="space-between" align="center" style="margin-bottom: 10px">
            <n-checkbox v-model:checked="hideRejected" size="small">
              隐藏已标记不符合（{{ rejectedInScanCount }}）
            </n-checkbox>
          </n-space>
          <n-grid :x-gap="12" :y-gap="12" cols="1 s:2 l:3" responsive="screen">
            <n-gi v-for="o in visibleOpportunities" :key="`${o.rank}-${o.title}`">
              <n-card
                size="small"
                embedded
                :class="{ 'opp-rejected': o.feedback?.verdict === 'bad' }"
              >
                <n-space justify="space-between" align="center">
                  <n-space :size="6" align="center">
                    <n-tag type="info" size="small" :bordered="false">#{{ o.rank }} · {{ o.confidence_score }}</n-tag>
                    <n-tag v-if="o.feedback?.verdict === 'good'" type="success" size="tiny">符合</n-tag>
                    <n-tag v-if="o.feedback?.verdict === 'bad'" type="error" size="tiny">不符合</n-tag>
                  </n-space>
                  <span style="font-size: 12px; opacity: 0.5">{{ o.country_label }}</span>
                </n-space>
                <div class="opp-title">{{ o.title }}</div>
                <div class="opp-desc">{{ o.one_liner }}</div>
                <div class="opp-meta">{{ o.genre_zh }} · {{ o.chart_type }}</div>
                <div v-if="o.feedback?.reason" class="opp-feedback-reason">反馈: {{ o.feedback.reason }}</div>
                <n-space :size="6" style="margin-top: 10px">
                  <n-button size="tiny" quaternary @click="openFeedbackModal(o, 'good')">符合</n-button>
                  <n-button size="tiny" quaternary type="warning" @click="openFeedbackModal(o, 'bad')">不符合</n-button>
                  <n-button v-if="o.feedback" size="tiny" quaternary @click="clearFeedback(o)">撤销</n-button>
                </n-space>
                <n-button
                  type="primary"
                  size="small"
                  block
                  style="margin-top: 8px"
                  :disabled="analyzing || o.feedback?.verdict === 'bad'"
                  @click="pick(o.rank)"
                >
                  选定并启动流水线
                </n-button>
              </n-card>
            </n-gi>
          </n-grid>
          <div v-if="analyzing" class="more-hint">
            <n-spin size="small" />
            <span>还在分析更多机会（{{ analysisProgress.done }}/{{ analysisProgress.total }} 批）…</span>
          </div>
        </template>
      </n-spin>
    </n-card>

    <n-modal
      v-model:show="showFeedbackModal"
      preset="dialog"
      title="标记为不符合"
      positive-text="提交反馈"
      negative-text="取消"
      @positive-click="() => submitFeedback()"
      @after-leave="pendingFeedback = null"
    >
      <div style="font-size: 13px; opacity: 0.75; margin-bottom: 10px">
        可选填写原因，系统将用于后续扫描/分析时排除类似方向。
      </div>
      <n-input
        v-model:value="feedbackReason"
        type="textarea"
        placeholder="如：缺乏榜单数据支撑、方向太泛、不适合独立开发者…"
        :rows="3"
      />
    </n-modal>
  </div>
</template>

<style scoped>
.scan-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: min-content;
  padding-bottom: 24px;
}

.scan-page.focus-opportunities {
  gap: 8px;
}

.focus-toolbar {
  flex-shrink: 0;
}

.focus-summary {
  font-size: 13px;
  opacity: 0.75;
}

.scan-top-grid {
  flex-shrink: 0;
  align-items: start;
}

.scan-panel-anchor,
.status-panel-shell {
  min-width: 0;
}

.status-panel-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 168px;
}

.status-panel-shell.collapsed {
  min-height: 0;
}

.status-panel-inner {
  flex: 1;
  min-height: 0;
}

.status-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.status-log-label {
  margin-top: 16px;
  margin-bottom: 6px;
  flex-shrink: 0;
}

.status-main {
  flex-shrink: 0;
}

.status-log-scroll {
  flex: 1;
  min-height: 72px;
}

.status-log-scroll :deep(.n-scrollbar) {
  max-height: none;
  height: 100%;
}

.status-log-scroll :deep(.n-scrollbar-container) {
  max-height: none !important;
}

.status-resize-handle {
  height: 12px;
  margin-top: 4px;
  flex-shrink: 0;
  cursor: ns-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0 0 8px 8px;
  user-select: none;
}

.status-resize-handle:hover,
.status-panel-shell.resizing .status-resize-handle {
  background: rgba(255, 255, 255, 0.06);
}

.resize-grip {
  width: 40px;
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.28);
}

.status-panel-shell.resizing .resize-grip {
  background: rgba(99, 102, 241, 0.75);
}

.status-summary {
  font-size: 12px;
  opacity: 0.55;
  max-width: min(280px, 40vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.opp-section {
  flex-shrink: 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.status-text {
  font-size: 13px;
  opacity: 0.85;
  min-height: 40px;
  line-height: 1.6;
}

.section-label {
  font-size: 11px;
  opacity: 0.5;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.stop-icon {
  width: 14px;
  height: 14px;
  display: block;
  color: #f87171;
}

.log-pre {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  opacity: 0.6;
  white-space: pre-wrap;
  line-height: 1.45;
  margin: 0;
}

.analyzing-hint {
  font-size: 13px;
  opacity: 0.65;
  padding: 24px 0;
  text-align: center;
}

.more-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 14px;
  font-size: 12px;
  opacity: 0.6;
}

.opp-title {
  font-size: 14px;
  font-weight: 600;
  margin-top: 10px;
  line-height: 1.35;
}

.opp-desc {
  font-size: 12px;
  opacity: 0.75;
  margin-top: 6px;
  line-height: 1.5;
}

.opp-meta {
  font-size: 11px;
  opacity: 0.45;
  margin-top: 6px;
}

.reanalyze-hint {
  font-size: 12px;
  opacity: 0.55;
  align-self: center;
}

.opp-rejected {
  opacity: 0.55;
}

.opp-feedback-reason {
  font-size: 11px;
  opacity: 0.6;
  margin-top: 8px;
  line-height: 1.45;
  font-style: italic;
}
</style>

<style>
body.status-panel-resizing {
  cursor: ns-resize !important;
  user-select: none !important;
}
</style>
