<script setup>
import { computed, ref } from 'vue'
import { NCard, NTag, NButton, NSpace, NProgress, useMessage } from 'naive-ui'

const props = defineProps({
  stages: { type: Array, default: () => [] },
  currentStage: String,
  runDetail: Object,
})

const emit = defineEmits(['select-stage', 'open-doc', 'close'])
const message = useMessage()
const copyBusy = ref(false)

const STAGE_SHORT = {
  scout: 'Scout',
  analyst: 'Analyst',
  pm: 'PM',
  designer: 'Design',
  dev_init: 'DevPlan',
  dev_scaffold: 'Scaffold',
  dev_code: 'Code',
  dev_verify: 'Verify',
  qa: 'QA',
  store: 'Store',
}

const PHASES = [
  { key: 'discover', label: '发现', stages: ['scout', 'analyst'] },
  { key: 'product', label: '产品', stages: ['pm', 'designer'] },
  { key: 'dev', label: '开发', stages: ['dev_init', 'dev_scaffold', 'dev_code', 'dev_verify'] },
  { key: 'release', label: '发布', stages: ['qa', 'store'] },
]

const runTitle = computed(() =>
  props.runDetail?.prd?.product_name
  || props.runDetail?.opportunity?.title
  || '流水线'
)

const runMeta = computed(() => {
  if (!props.runDetail) return ''
  return `${props.runDetail.current_stage} · ${props.runDetail.seed_keyword || '—'}`
})

async function copyRunId() {
  const id = props.runDetail?.id
  if (!id || copyBusy.value) return
  copyBusy.value = true
  try {
    await navigator.clipboard.writeText(id)
    message.success('流水线 ID 已复制')
  } catch {
    message.error('复制失败，请手动复制')
  } finally {
    copyBusy.value = false
  }
}

const statusType = (s) => ({
  running: 'info',
  paused: 'warning',
  completed: 'success',
  failed: 'error',
}[s] || 'default')

const doneCount = computed(() =>
  props.stages.filter((s) => s.status === 'done' || s.review_status === 'approved').length
)

const progressPct = computed(() => {
  if (!props.stages.length) return 0
  return Math.round((doneCount.value / props.stages.length) * 100)
})

function shortLabel(s) {
  return STAGE_SHORT[s.stage] || s.label
}

function fullLabel(s) {
  return s.label
}

function reviewType(s) {
  if (s.review_status === 'approved') return 'success'
  if (s.review_status === 'pending' && s.has_output) return 'warning'
  if (s.review_status === 'rejected') return 'error'
  return 'default'
}

function reviewText(s) {
  if (s.review_status === 'approved') return '已通过'
  if (s.review_status === 'pending' && s.has_output) return '待审'
  if (s.review_status === 'rejected') return '已拒绝'
  return null
}

function nodeStatusType(s) {
  if (s.status === 'running') return 'running'
  if (s.stage === props.currentStage) return 'active'
  if (s.status === 'done' || s.review_status === 'approved') return 'done'
  if (s.status === 'failed') return 'failed'
  if (s.has_output) return 'review'
  return 'pending'
}

function isExecuting(s) {
  return s.status === 'running'
}

function stagesInPhase(phase) {
  return props.stages.filter((s) => phase.stages.includes(s.stage))
}

function phaseDone(phase) {
  const rows = stagesInPhase(phase)
  if (!rows.length) return false
  return rows.every((s) => s.status === 'done' || s.review_status === 'approved')
}

function phaseActive(phase) {
  return phase.stages.includes(props.currentStage)
}
</script>

<template>
  <n-space vertical :size="16" class="pipeline-track">
    <n-card size="small" :bordered="false">
      <n-space justify="space-between" align="center" wrap>
        <div class="run-head">
          <div class="run-title">{{ runTitle }}</div>
          <div v-if="runDetail?.id" class="run-id-row">
            <span class="run-id">{{ runDetail.id }}</span>
            <n-button
              size="tiny"
              quaternary
              circle
              title="复制流水线 ID"
              aria-label="复制流水线 ID"
              :loading="copyBusy"
              @click="copyRunId"
            >
              <svg class="copy-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
            </n-button>
          </div>
          <div v-if="runMeta" class="run-meta">{{ runMeta }}</div>
        </div>
        <n-space align="center">
          <n-button size="small" quaternary @click="emit('close')">返回扫描</n-button>
          <n-tag v-if="runDetail?.status" :type="statusType(runDetail.status)" size="small">
            {{ runDetail.status }}
          </n-tag>
        </n-space>
      </n-space>
    </n-card>

    <n-card title="流水线进度" size="small" class="progress-card">
      <div class="progress-bar">
        <n-progress
          type="line"
          :percentage="progressPct"
          :height="6"
          :border-radius="3"
          :show-indicator="false"
        />
        <span class="progress-label">{{ doneCount }}/{{ stages.length }}</span>
      </div>

      <div class="phase-list">
        <section
          v-for="phase in PHASES"
          :key="phase.key"
          class="phase-block"
          :class="{ 'phase-active': phaseActive(phase), 'phase-done': phaseDone(phase) }"
        >
          <div class="phase-head">
            <span class="phase-name">{{ phase.label }}</span>
            <span class="phase-count">
              {{ stagesInPhase(phase).filter((s) => s.status === 'done' || s.review_status === 'approved').length }}
              / {{ stagesInPhase(phase).length }}
            </span>
          </div>

          <div class="pipeline-grid">
            <div
              v-for="s in stagesInPhase(phase)"
              :key="s.stage"
              class="pipeline-node-wrap"
            >
              <div
                class="pipeline-node"
                :class="[nodeStatusType(s), { executing: isExecuting(s) }]"
                @click="emit('select-stage', s.stage)"
              >
                <div class="node-top">
                  <span class="node-short" :title="fullLabel(s)">{{ shortLabel(s) }}</span>
                  <n-tag v-if="reviewText(s)" :type="reviewType(s)" size="tiny" class="node-tag">
                    {{ reviewText(s) }}
                  </n-tag>
                </div>

                <div v-if="s.documents?.length" class="doc-list">
                  <n-button
                    v-for="d in s.documents"
                    :key="d.name"
                    size="tiny"
                    :disabled="!s.has_output"
                    secondary
                    block
                    class="doc-btn"
                    :title="d.label || d.name"
                    @click.stop="s.has_output && emit('open-doc', s.stage, d.name)"
                  >
                    {{ d.label || d.name }}
                  </n-button>
                </div>
                <span v-else class="node-empty">无文档</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </n-card>
  </n-space>
</template>

<style scoped>
.pipeline-track {
  max-width: 100%;
  min-width: 0;
}

.run-head {
  min-width: 0;
  flex: 1;
}

.run-title {
  font-size: 16px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-id-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  min-width: 0;
}

.run-id {
  font-size: 12px;
  font-family: ui-monospace, monospace;
  opacity: 0.62;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.copy-icon {
  width: 14px;
  height: 14px;
  opacity: 0.75;
}

.run-meta {
  font-size: 12px;
  opacity: 0.5;
  margin-top: 4px;
  font-family: ui-monospace, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-card :deep(.n-card__content) {
  overflow: hidden;
}

.progress-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-bar :deep(.n-progress) {
  flex: 1;
  min-width: 0;
}

.progress-label {
  flex-shrink: 0;
  font-size: 12px;
  font-family: ui-monospace, monospace;
  opacity: 0.55;
}

.phase-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 16px;
}

.phase-block {
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.02);
}

.phase-block.phase-active {
  border-color: rgba(99, 102, 241, 0.35);
  background: rgba(99, 102, 241, 0.06);
}

.phase-block.phase-done:not(.phase-active) {
  opacity: 0.72;
}

.phase-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
}

.phase-name {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  opacity: 0.55;
}

.phase-count {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  opacity: 0.45;
}

.pipeline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
  min-width: 0;
}

.pipeline-node-wrap {
  position: relative;
  min-width: 0;
}

.pipeline-node {
  position: relative;
  z-index: 0;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(0, 0, 0, 0.15);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
  overflow: hidden;
  isolation: isolate;
}

/* 跑马灯沿当前卡片实际边框走（mask 挖空内容区，高度随文档按钮变化） */
.pipeline-node.executing::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 2px;
  background: conic-gradient(
    from var(--pipeline-ring-angle, 0deg),
    transparent 0deg 250deg,
    rgba(99, 102, 241, 0.15) 270deg,
    rgba(129, 140, 248, 0.95) 300deg,
    rgba(34, 211, 238, 1) 330deg,
    rgba(129, 140, 248, 0.95) 350deg,
    rgba(99, 102, 241, 0.15) 370deg,
    transparent 360deg
  );
  -webkit-mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  animation: pipeline-ring-spin 1.6s linear infinite;
  pointer-events: none;
  z-index: 2;
}

.pipeline-node.executing {
  border-color: rgba(129, 140, 248, 0.35);
  background: rgba(99, 102, 241, 0.12);
  box-shadow:
    0 0 12px rgba(99, 102, 241, 0.18),
    inset 0 0 20px rgba(99, 102, 241, 0.06);
}

.pipeline-node.executing .node-top,
.pipeline-node.executing .doc-list,
.pipeline-node.executing .node-empty {
  position: relative;
  z-index: 1;
}

@property --pipeline-ring-angle {
  syntax: '<angle>';
  initial-value: 0deg;
  inherits: false;
}

@keyframes pipeline-ring-spin {
  to {
    --pipeline-ring-angle: 360deg;
  }
}

.pipeline-node:hover {
  border-color: rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.04);
}

.pipeline-node.active {
  border-color: rgba(99, 102, 241, 0.55);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.25);
  background: rgba(99, 102, 241, 0.1);
}

.pipeline-node.running {
  border-color: rgba(129, 140, 248, 0.45);
}

.pipeline-node.done {
  border-color: rgba(34, 197, 94, 0.25);
}

.pipeline-node.review {
  border-color: rgba(234, 179, 8, 0.3);
}

.node-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  min-width: 0;
}

.node-short {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.node-tag {
  flex-shrink: 0;
  transform: scale(0.92);
  transform-origin: right center;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
  min-width: 0;
}

.doc-btn {
  max-width: 100%;
}

.doc-btn :deep(.n-button__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
  max-width: 100%;
}

.node-empty {
  display: block;
  font-size: 10px;
  opacity: 0.35;
  margin-top: 6px;
}

.pipeline-node.failed {
  border-color: rgba(239, 68, 68, 0.35);
}

@media (prefers-reduced-motion: reduce) {
  .pipeline-node.executing::before {
    animation: none;
    background: linear-gradient(
      135deg,
      rgba(99, 102, 241, 0.55),
      rgba(34, 211, 238, 0.45)
    );
    -webkit-mask: none;
    mask: none;
    padding: 0;
    opacity: 0.45;
  }
}

@media (max-width: 640px) {
  .pipeline-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
