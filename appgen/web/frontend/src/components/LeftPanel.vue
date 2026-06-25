<script setup>
import { computed } from 'vue'
import {
  NCard,
  NEmpty,
  NTag,
  NButton,
  NInput,
  NSpace,
  NDivider,
  NScrollbar,
} from 'naive-ui'
import CollapsiblePanel from './CollapsiblePanel.vue'

const props = defineProps({
  runs: { type: Array, default: () => [] },
  currentRunId: String,
  stage: Object,
  stagePayload: Object,
  reviewNotes: String,
  logs: { type: Array, default: () => [] },
  autoReview: { type: Boolean, default: false },
  runsCollapsed: { type: Boolean, default: false },
})

const emit = defineEmits([
  'select-run',
  'close-run',
  'open-doc',
  'update:reviewNotes',
  'review',
  'update:runsCollapsed',
])

const statusType = (s) => ({
  running: 'info',
  paused: 'warning',
  completed: 'success',
  failed: 'error',
}[s] || 'default')

const reviewTag = computed(() => {
  const r = props.stage
  if (!r) return null
  if (r.review_status === 'pending' && r.has_output) return { type: 'warning', text: '待 Review' }
  if (r.review_status === 'approved') return { type: 'success', text: '已通过' }
  if (r.review_status === 'rejected') return { type: 'error', text: '已拒绝' }
  return r.has_output
    ? { type: 'success', text: '已产出' }
    : { type: 'default', text: '未产出' }
})

const showReview = computed(
  () => !props.autoReview && props.stage?.review_status === 'pending' && props.stage?.has_output
)

const runsSummary = computed(() => {
  if (!props.runs.length) return ''
  const active = props.currentRunId
    ? props.runs.find((r) => r.id === props.currentRunId)
    : null
  if (active) {
    return active.product_name || active.opportunity_title || active.seed_keyword || active.id
  }
  return `${props.runs.length} 条运行`
})
</script>

<template>
  <n-space vertical :size="12" class="left-panel">
    <CollapsiblePanel
      :collapsed="runsCollapsed"
      title="流水线运行"
      @update:collapsed="emit('update:runsCollapsed', $event)"
    >
      <template #header-extra>
        <span v-if="runsCollapsed && runsSummary" class="runs-summary">{{ runsSummary }}</span>
        <n-tag v-if="runs.length && !runsCollapsed" size="tiny" :bordered="false" type="default">
          {{ runs.length }}
        </n-tag>
      </template>

      <n-empty v-if="!runs.length" description="暂无运行" size="small" />
      <n-space v-else vertical :size="6">
        <div
          v-for="r in runs"
          :key="r.id"
          class="run-item"
          :class="{ active: r.id === currentRunId }"
          @click="emit('select-run', r.id)"
        >
          <div class="run-row">
            <span class="run-id">{{ r.id }}</span>
            <n-tag :type="statusType(r.status)" size="small" :bordered="false">{{ r.status }}</n-tag>
          </div>
          <div class="run-name">{{ r.product_name || r.opportunity_title || r.seed_keyword || '—' }}</div>
          <n-tag v-if="r.pending_review" type="warning" size="tiny" style="margin-top: 4px">
            待审 {{ r.pending_review }}
          </n-tag>
        </div>
      </n-space>
    </CollapsiblePanel>

    <n-card v-if="currentRunId && stage" title="当前节点" size="small" :bordered="false" class="stage-card">
      <template #header-extra>
        <n-button size="tiny" quaternary @click="emit('close-run')">关闭</n-button>
      </template>
      <div class="stage-head">
        <span class="stage-name">{{ stage.label }}</span>
        <n-tag v-if="reviewTag" :type="reviewTag.type" size="small">{{ reviewTag.text }}</n-tag>
      </div>

      <div v-if="stagePayload?.summary && stagePayload.summary !== '暂无摘要'" class="summary">
        {{ stagePayload.summary }}
      </div>

      <div v-if="stagePayload?.review?.notes && stagePayload.review.status !== 'pending'" class="review-note">
        {{ stagePayload.review.status }} · {{ stagePayload.review.notes }}
      </div>

      <template v-if="stagePayload?.documents?.length">
        <n-divider style="margin: 12px 0" />
        <div class="section-label">文档产物</div>
        <div class="doc-grid">
          <n-button
            v-for="d in stagePayload.documents"
            :key="d.name"
            size="tiny"
            secondary
            class="doc-chip"
            :title="d.label"
            @click="emit('open-doc', d.name)"
          >
            {{ d.label }}
          </n-button>
        </div>
      </template>

      <div v-if="autoReview" class="summary auto-hint">
        一键通过已开启，节点产物将自动进入下一阶段
      </div>

      <template v-if="showReview">
        <n-divider style="margin: 12px 0" />
        <div class="section-label">Review 反馈</div>
        <n-input
          type="textarea"
          :value="reviewNotes"
          placeholder="修订/拒绝时必填"
          :rows="3"
          style="margin-top: 6px"
          @update:value="emit('update:reviewNotes', $event)"
        />
        <n-space :size="8" style="margin-top: 8px">
          <n-button size="small" type="primary" @click="emit('review', 'approve')">批准</n-button>
          <n-button size="small" @click="emit('review', 'revise')">修订</n-button>
          <n-button size="small" type="error" ghost @click="emit('review', 'reject')">拒绝</n-button>
        </n-space>
      </template>

      <template v-if="logs.length">
        <n-divider style="margin: 12px 0" />
        <div class="section-label">运行日志</div>
        <n-scrollbar style="max-height: 100px; margin-top: 6px">
          <pre class="log-pre">{{ logs.join('\n') }}</pre>
        </n-scrollbar>
      </template>
    </n-card>
  </n-space>
</template>

<style scoped>
.left-panel {
  min-width: 0;
}

.runs-summary {
  font-size: 12px;
  opacity: 0.55;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-item {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s;
}

.run-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.run-item.active {
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.35);
}

.run-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}

.run-id {
  font-size: 12px;
  font-family: ui-monospace, monospace;
  opacity: 0.7;
}

.run-name {
  font-size: 12px;
  margin-top: 4px;
  opacity: 0.85;
  line-height: 1.4;
}

.stage-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.stage-name {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.doc-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  min-width: 0;
}

.doc-chip {
  max-width: 100%;
}

.doc-chip :deep(.n-button__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.section-label {
  font-size: 11px;
  opacity: 0.5;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.auto-hint {
  font-size: 12px;
  line-height: 1.5;
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  color: rgba(99, 102, 241, 0.85);
  border: 1px solid rgba(99, 102, 241, 0.25);
  background: rgba(99, 102, 241, 0.08);
}

.summary,
.review-note {
  font-size: 12px;
  line-height: 1.5;
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
}

.log-pre {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  opacity: 0.6;
  white-space: pre-wrap;
  line-height: 1.45;
  margin: 0;
}
</style>
