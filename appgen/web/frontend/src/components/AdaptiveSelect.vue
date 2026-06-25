<script setup>
import { computed, ref, watch } from 'vue'
import {
  NSelect,
  NInput,
  NModal,
  NCheckbox,
  NButton,
  NScrollbar,
  NEmpty,
} from 'naive-ui'

const ADAPTIVE_SELECT_THRESHOLD = 8

const props = defineProps({
  value: { type: [String, Number, Array, null], default: null },
  options: { type: Array, default: () => [] },
  multiple: { type: Boolean, default: false },
  filterable: { type: Boolean, default: true },
  placeholder: { type: String, default: '请选择' },
  disabled: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  maxTagCount: { type: [String, Number], default: undefined },
  modalTitle: { type: String, default: '请选择' },
  searchPlaceholder: { type: String, default: '搜索…' },
  richOptions: { type: Boolean, default: false },
  style: { type: [String, Object, Array], default: undefined },
})

const emit = defineEmits(['update:value'])

const showModal = ref(false)
const search = ref('')
const draftValue = ref(null)

const useModal = computed(
  () => props.richOptions || props.options.length >= ADAPTIVE_SELECT_THRESHOLD
)

const filteredOptions = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((opt) => {
    if (opt.searchText) {
      return String(opt.searchText).toLowerCase().includes(q)
    }
    const label = String(opt.label ?? '').toLowerCase()
    const value = String(opt.value ?? '').toLowerCase()
    return label.includes(q) || value.includes(q)
  })
})

const modalWidth = computed(() => {
  const n = filteredOptions.value.length
  if (n >= 24) return 'min(920px, 96vw)'
  if (n >= 12) return 'min(780px, 94vw)'
  return 'min(640px, 92vw)'
})

const gridMinWidth = computed(() => {
  if (props.richOptions) return '220px'
  const n = filteredOptions.value.length
  if (n >= 24) return '148px'
  if (n >= 12) return '156px'
  return '168px'
})

const draftSet = computed(() => {
  const vals = Array.isArray(draftValue.value) ? draftValue.value : []
  return new Set(vals)
})

function optionLabel(val) {
  const hit = props.options.find((o) => o.value === val)
  return hit?.label ?? String(val)
}

const summaryText = computed(() => {
  if (props.multiple) {
    const vals = Array.isArray(props.value) ? props.value : []
    if (!vals.length) return ''
    if (vals.length <= 3) return vals.map(optionLabel).join('、')
    return `${vals.map(optionLabel).slice(0, 2).join('、')} 等 ${vals.length} 项`
  }
  if (props.value === null || props.value === undefined || props.value === '') return ''
  return optionLabel(props.value)
})

const hasValue = computed(() => {
  if (props.multiple) return Array.isArray(props.value) && props.value.length > 0
  return props.value !== null && props.value !== undefined && props.value !== ''
})

function openModal() {
  if (props.disabled) return
  search.value = ''
  draftValue.value = props.multiple
    ? [...(Array.isArray(props.value) ? props.value : [])]
    : props.value
  showModal.value = true
}

function confirmMulti() {
  emit('update:value', [...(draftValue.value || [])])
  showModal.value = false
}

function pickSingle(val) {
  emit('update:value', val)
  showModal.value = false
}

function toggleMultiOption(val) {
  const arr = [...(Array.isArray(draftValue.value) ? draftValue.value : [])]
  const idx = arr.indexOf(val)
  if (idx >= 0) arr.splice(idx, 1)
  else arr.push(val)
  draftValue.value = arr
}

function isDraftSelected(val) {
  return draftSet.value.has(val)
}

function clearDraftSelection() {
  draftValue.value = []
}

function selectAllFiltered() {
  const filteredVals = filteredOptions.value.map((o) => o.value)
  const current = new Set(Array.isArray(draftValue.value) ? draftValue.value : [])
  for (const val of filteredVals) current.add(val)
  draftValue.value = [...current]
}

function invertFilteredSelection() {
  const filteredVals = filteredOptions.value.map((o) => o.value)
  const filteredSet = new Set(filteredVals)
  const current = Array.isArray(draftValue.value) ? draftValue.value : []
  const kept = current.filter((val) => !filteredSet.has(val))
  const inverted = filteredVals.filter((val) => !current.includes(val))
  draftValue.value = [...kept, ...inverted]
}

function clearValue(event) {
  event?.stopPropagation?.()
  emit('update:value', props.multiple ? [] : null)
}

watch(showModal, (open) => {
  if (!open) search.value = ''
})
</script>

<template>
  <n-select
    v-if="!useModal"
    :value="value"
    :options="options"
    :multiple="multiple"
    :filterable="filterable"
    :placeholder="placeholder"
    :disabled="disabled"
    :clearable="clearable"
    :max-tag-count="maxTagCount"
    :style="style"
    @update:value="emit('update:value', $event)"
  />

  <div v-else class="adaptive-select" :style="style">
    <div
      class="adaptive-trigger"
      :class="{ disabled, 'has-value': hasValue }"
      tabindex="0"
      role="button"
      @click="openModal"
      @keydown.enter.prevent="openModal"
      @keydown.space.prevent="openModal"
    >
      <span v-if="hasValue" class="adaptive-value">{{ summaryText }}</span>
      <span v-else class="adaptive-placeholder">{{ placeholder }}</span>
      <span class="adaptive-actions">
        <button
          v-if="clearable && hasValue && !disabled"
          type="button"
          class="adaptive-clear"
          aria-label="清空"
          @click="clearValue"
        >
          ×
        </button>
        <span class="adaptive-chevron" aria-hidden="true">▾</span>
      </span>
    </div>

    <n-modal
      v-model:show="showModal"
      preset="card"
      :title="modalTitle"
      class="adaptive-select-modal"
      :style="{ width: modalWidth }"
      :mask-closable="!multiple"
    >
      <div v-if="filterable" class="adaptive-search">
        <n-input
          v-model:value="search"
          class="adaptive-search-input"
          :placeholder="searchPlaceholder"
          clearable
          size="medium"
        />
      </div>

      <n-scrollbar class="adaptive-options-scroll">
        <n-empty v-if="!filteredOptions.length" description="无匹配项" size="small" style="padding: 24px 0" />
        <div v-else-if="multiple" class="option-grid" :style="{ '--option-col-min': gridMinWidth }">
          <div
            v-for="opt in filteredOptions"
            :key="String(opt.value)"
            class="option-cell option-cell--check"
            :class="{ selected: isDraftSelected(opt.value), 'option-cell--rich': richOptions }"
            role="checkbox"
            :aria-checked="isDraftSelected(opt.value)"
            tabindex="0"
            @click="toggleMultiOption(opt.value)"
            @keydown.enter.prevent="toggleMultiOption(opt.value)"
            @keydown.space.prevent="toggleMultiOption(opt.value)"
          >
            <n-checkbox
              class="option-checkbox"
              :checked="isDraftSelected(opt.value)"
              :focusable="false"
              tabindex="-1"
            />
            <span v-if="richOptions" class="option-rich">
              <span
                v-if="opt.statusLabel"
                class="rich-status-badge"
                :class="{ ok: opt.statusCompleted }"
              >{{ opt.statusLabel }}</span>
              <span v-if="opt.keyword" class="rich-line rich-name">{{ opt.keyword }}</span>
              <span class="rich-line rich-id">{{ opt.value }}</span>
              <span class="rich-line rich-meta">{{ opt.statusLine }}</span>
              <span class="rich-line rich-date">{{ opt.dateLine }}</span>
            </span>
            <span v-else class="option-label">{{ opt.label }}</span>
          </div>
        </div>
        <div v-else class="option-grid" :style="{ '--option-col-min': gridMinWidth }">
          <button
            v-for="opt in filteredOptions"
            :key="String(opt.value)"
            type="button"
            class="option-cell option-cell--single"
            :class="{ active: value === opt.value, 'option-cell--rich': richOptions }"
            @click="pickSingle(opt.value)"
          >
            <template v-if="richOptions">
              <span
                v-if="opt.statusLabel"
                class="rich-status-badge"
                :class="{ ok: opt.statusCompleted }"
              >{{ opt.statusLabel }}</span>
              <span v-if="opt.keyword" class="rich-line rich-name">{{ opt.keyword }}</span>
              <span class="rich-line rich-id">{{ opt.value }}</span>
              <span class="rich-line rich-meta">{{ opt.statusLine }}</span>
              <span class="rich-line rich-date">{{ opt.dateLine }}</span>
            </template>
            <template v-else>{{ opt.label }}</template>
          </button>
        </div>
      </n-scrollbar>

      <template v-if="multiple" #footer>
        <div class="modal-footer">
          <div class="bulk-actions">
            <n-button size="small" quaternary :disabled="!filteredOptions.length" @click="selectAllFiltered">
              全选
            </n-button>
            <n-button size="small" quaternary @click="clearDraftSelection">清除</n-button>
            <n-button size="small" quaternary :disabled="!filteredOptions.length" @click="invertFilteredSelection">
              反选
            </n-button>
            <span v-if="search.trim()" class="bulk-hint">筛选 {{ filteredOptions.length }} 项</span>
          </div>
          <div class="modal-footer-actions">
            <n-button @click="showModal = false">取消</n-button>
            <n-button type="primary" @click="confirmMulti">确定</n-button>
          </div>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.adaptive-select {
  width: 100%;
  min-width: 0;
}

.adaptive-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.adaptive-trigger:hover:not(.disabled) {
  border-color: rgba(99, 102, 241, 0.55);
}

.adaptive-trigger.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.adaptive-value,
.adaptive-placeholder {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  line-height: 1.4;
  text-align: left;
}

.adaptive-placeholder {
  opacity: 0.45;
}

.adaptive-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.adaptive-clear {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.45);
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  cursor: pointer;
}

.adaptive-clear:hover {
  color: rgba(255, 255, 255, 0.85);
}

.adaptive-chevron {
  font-size: 12px;
  opacity: 0.55;
}

.adaptive-search {
  display: flex;
  justify-content: center;
  width: 100%;
  margin-bottom: 12px;
}

.adaptive-search-input {
  width: 100%;
  max-width: 660px;
}

@media (min-width: 640px) {
  .adaptive-search-input {
    width: 92%;
  }
}

.adaptive-search-input :deep(.n-input-wrapper) {
  min-height: 32px;
}

.adaptive-search-input :deep(.n-input__input-el) {
  height: 30px;
  line-height: 30px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.bulk-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  flex: 1;
  min-width: 0;
}

.modal-footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.bulk-hint {
  font-size: 12px;
  opacity: 0.45;
  white-space: nowrap;
}

.adaptive-options-scroll {
  max-height: min(58vh, 480px);
}

.option-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--option-col-min, 168px), 1fr));
  gap: 6px;
  align-items: stretch;
}

.option-cell {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-height: 38px;
  padding: 8px 10px;
  border-radius: 8px;
  text-align: left;
  font-size: 13px;
  line-height: 1.4;
}

.option-cell--check {
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease, border-color 0.15s ease;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.option-cell--check:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}

.option-cell--check.selected {
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.35);
}

.option-checkbox {
  pointer-events: none;
  flex-shrink: 0;
}

.option-cell--single {
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  color: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
  justify-content: flex-start;
  word-break: break-word;
}

.option-cell--single:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.12);
}

.option-cell--single.active {
  background: rgba(99, 102, 241, 0.18);
  border-color: rgba(99, 102, 241, 0.45);
  color: rgba(255, 255, 255, 0.95);
}

.option-label {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.option-rich {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.option-cell--rich {
  position: relative;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-height: 72px;
  padding: 10px 52px 10px 12px;
}

.rich-status-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.35;
  font-weight: 500;
  white-space: nowrap;
  background: rgba(239, 68, 68, 0.16);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.38);
}

.rich-status-badge.ok {
  background: rgba(34, 197, 94, 0.16);
  color: #4ade80;
  border-color: rgba(34, 197, 94, 0.38);
}

.rich-line {
  display: block;
  width: 100%;
  line-height: 1.35;
  word-break: break-all;
}

.rich-name {
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}

.rich-id {
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  opacity: 0.72;
}

.rich-meta {
  font-size: 12px;
  opacity: 0.78;
}

.rich-date {
  font-size: 11px;
  opacity: 0.5;
}
</style>
