<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCollapse,
  NCollapseItem,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSpace,
  NSwitch,
  NDynamicInput,
  NDivider,
  NAlert,
  useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import AdaptiveSelect from './AdaptiveSelect.vue'

const emit = defineEmits(['back', 'saved'])
const message = useMessage()

const loading = ref(false)
const saving = ref(false)

const form = reactive({
  auto_review_default: false,
  llm_provider_mode: 'auto',
  llm_providers: [],
  rss_marketing_url: '',
  rss_legacy_top_url: '',
  rss_legacy_genre_url: '',
  legacy_top_chart_types: [],
  scan_limit_min: 1,
  scan_limit_max: 100,
  default_scan_limit: 10,
  default_scan_enrich: 5,
  default_charts: [],
  scan_concurrency: 10,
  scan_max_concurrency: 20,
  analyze_batch_size: 6,
  analyze_concurrency: 3,
  analyze_max_snapshots: 40,
  analyze_max_snapshots_min: 10,
  analyze_max_snapshots_max: 120,
  cursor_launch_stagger_ms: 2500,
  cursor_launch_jitter_ms: 400,
  cursor_chat_timeout_sec: 600,
  cursor_chat_timeout_sec_min: 60,
  cursor_chat_timeout_sec_max: 3600,
  cursor_chat_idle_timeout_sec: 120,
  cursor_chat_idle_timeout_sec_min: 30,
  cursor_chat_idle_timeout_sec_max: 600,
  pipeline_resume_stale_minutes: 8,
  pipeline_resume_stale_minutes_min: 1,
  pipeline_resume_stale_minutes_max: 120,
  review_mode: 'cli',
  http_proxy: '',
  serper_api_key: '',
  workspace: './workspace',
  host: '127.0.0.1',
  port: 8787,
  cursor_cwd: '',
  default_region_preset: 'us-eu',
  popular_genre_ids: [],
  store_regions: [],
  region_presets: [],
  genres: [],
})

const providerOptions = [
  { label: 'Cursor', value: 'cursor' },
  { label: 'OpenAI 兼容', value: 'openai' },
]

const modeOptions = [
  { label: '自动（按列表顺序）', value: 'auto' },
  { label: '仅 Cursor', value: 'cursor' },
  { label: '仅 OpenAI', value: 'openai' },
  { label: 'Mock', value: 'mock' },
]

const reviewModeOptions = [
  { label: 'CLI 确认', value: 'cli' },
  { label: 'Web 确认', value: 'web' },
  { label: '自动通过', value: 'auto' },
]

const regionPresetOptions = computed(() =>
  form.region_presets
    .filter((p) => p.key?.trim())
    .map((p) => ({ label: p.key.trim(), value: p.key.trim() }))
)

const storeRegionSelectOptions = computed(() =>
  form.store_regions
    .filter((r) => r.code?.trim())
    .map((r) => ({
      label: `${r.name_zh || r.name} (${r.code})`,
      value: r.code.trim().toLowerCase(),
    }))
)

const genreSelectOptions = computed(() =>
  form.genres
    .filter((g) => g.id != null && g.name_zh)
    .map((g) => ({
      label: `${g.name_zh} · ${g.name} · ${g.id}`,
      value: g.id,
    }))
)

function newProvider() {
  return { provider: 'cursor', api_key: '', base_url: 'https://api.openai.com/v1', model: '' }
}

function newStoreRegion() {
  return { code: '', name: '', name_zh: '' }
}

function newRegionPreset() {
  return { key: '', codes: [] }
}

function newGenre() {
  return { id: null, name: '', name_zh: '', search_term: '' }
}

function cloneGenre(g) {
  return {
    id: g.id,
    name: g.name || '',
    name_zh: g.name_zh || '',
    search_term: g.search_term || '',
  }
}

function cloneStoreRegion(r) {
  return {
    code: (r.code || '').toLowerCase(),
    name: r.name || '',
    name_zh: r.name_zh || '',
  }
}

function applyData(data) {
  form.auto_review_default = !!data.auto_review_default
  form.llm_provider_mode = data.llm_provider_mode || 'auto'
  form.llm_providers = (data.llm_providers || []).map((p) => ({
    provider: p.provider,
    api_key: '',
    base_url: p.base_url || '',
    model: p.model || '',
    _preview: p.api_key_preview,
    _set: p.api_key_set,
  }))
  if (!form.llm_providers.length) form.llm_providers = [newProvider()]
  form.rss_marketing_url = data.rss_marketing_url || ''
  form.rss_legacy_top_url = data.rss_legacy_top_url || ''
  form.rss_legacy_genre_url = data.rss_legacy_genre_url || ''
  form.legacy_top_chart_types = [...(data.legacy_top_chart_types || [])]
  form.scan_limit_min = data.scan_limit_min
  form.scan_limit_max = data.scan_limit_max
  form.default_scan_limit = data.default_scan_limit
  form.default_scan_enrich = data.default_scan_enrich
  form.default_charts = [...(data.default_charts || [])]
  form.scan_concurrency = data.scan_concurrency
  form.scan_max_concurrency = data.scan_max_concurrency
  form.analyze_batch_size = data.analyze_batch_size
  form.analyze_concurrency = data.analyze_concurrency
  form.analyze_max_snapshots = data.analyze_max_snapshots ?? 40
  form.analyze_max_snapshots_min = data.analyze_max_snapshots_min ?? 10
  form.analyze_max_snapshots_max = data.analyze_max_snapshots_max ?? 120
  form.cursor_launch_stagger_ms = data.cursor_launch_stagger_ms
  form.cursor_launch_jitter_ms = data.cursor_launch_jitter_ms
  form.cursor_chat_timeout_sec = data.cursor_chat_timeout_sec ?? 600
  form.cursor_chat_timeout_sec_min = data.cursor_chat_timeout_sec_min ?? 60
  form.cursor_chat_timeout_sec_max = data.cursor_chat_timeout_sec_max ?? 3600
  form.cursor_chat_idle_timeout_sec = data.cursor_chat_idle_timeout_sec ?? 120
  form.cursor_chat_idle_timeout_sec_min = data.cursor_chat_idle_timeout_sec_min ?? 30
  form.cursor_chat_idle_timeout_sec_max = data.cursor_chat_idle_timeout_sec_max ?? 600
  form.pipeline_resume_stale_minutes = data.pipeline_resume_stale_minutes ?? 8
  form.pipeline_resume_stale_minutes_min = data.pipeline_resume_stale_minutes_min ?? 1
  form.pipeline_resume_stale_minutes_max = data.pipeline_resume_stale_minutes_max ?? 120
  form.review_mode = data.review_mode
  form.http_proxy = data.http_proxy || ''
  form.serper_api_key = ''
  form._serper_preview = data.serper_api_key_preview
  form._serper_set = data.serper_api_key_set
  form.workspace = data.workspace
  form.host = data.host
  form.port = data.port
  form.cursor_cwd = data.cursor_cwd || ''
  form.default_region_preset = data.default_region_preset
  form.popular_genre_ids = [...(data.popular_genre_ids || [])]
  form.store_regions = (data.store_regions || []).map(cloneStoreRegion)
  form.region_presets = Object.entries(data.region_presets || {}).map(([key, codes]) => ({
    key,
    codes: [...codes],
  }))
  form.genres = (data.genres || []).map(cloneGenre)
}

function validateCatalog() {
  const allPresetKeys = new Set(
    form.region_presets.map((p) => p.key?.trim()).filter(Boolean)
  )
  const defPreset = (form.default_region_preset || '').trim()
  if (defPreset && !allPresetKeys.has(defPreset)) {
    throw new Error(`默认区域预设「${defPreset}」不存在，请从已有预设中选择`)
  }

  const codes = new Set()
  for (const r of form.store_regions) {
    const code = (r.code || '').trim().toLowerCase()
    if (!code) throw new Error('店面国家：国家代码不能为空')
    if (codes.has(code)) throw new Error(`店面国家：代码重复 ${code}`)
    codes.add(code)
    if (!(r.name || '').trim()) throw new Error(`店面国家 ${code}：英文名不能为空`)
    if (!(r.name_zh || '').trim()) throw new Error(`店面国家 ${code}：中文名不能为空`)
  }

  const genreIds = new Set()
  for (const g of form.genres) {
    if (g.id == null || Number.isNaN(Number(g.id))) throw new Error('品类：ID 不能为空')
    const id = Number(g.id)
    if (genreIds.has(id)) throw new Error(`品类：ID 重复 ${id}`)
    genreIds.add(id)
    if (!(g.name || '').trim()) throw new Error(`品类 ${id}：英文名不能为空`)
    if (!(g.name_zh || '').trim()) throw new Error(`品类 ${id}：中文名不能为空`)
    if (!(g.search_term || '').trim()) throw new Error(`品类 ${id}：搜索词不能为空`)
  }

  const presetKeys = new Set()
  for (const p of form.region_presets) {
    const key = (p.key || '').trim()
    if (!key) throw new Error('区域预设：名称不能为空')
    if (presetKeys.has(key)) throw new Error(`区域预设：名称重复 ${key}`)
    presetKeys.add(key)
    if (!p.codes?.length) throw new Error(`区域预设「${key}」：至少选择一个国家`)
    for (const code of p.codes) {
      if (!codes.has(code)) throw new Error(`区域预设「${key}」：未知国家代码 ${code}`)
    }
  }
}

function buildPayload() {
  validateCatalog()
  const region_presets = Object.fromEntries(
    form.region_presets.map((p) => [p.key.trim(), [...p.codes]])
  )
  return {
    auto_review_default: form.auto_review_default,
    llm_provider_mode: form.llm_provider_mode,
    llm_providers: form.llm_providers.map((p) => ({
      provider: p.provider,
      api_key: p.api_key || '',
      base_url: p.base_url || '',
      model: p.model || '',
    })),
    rss_marketing_url: form.rss_marketing_url,
    rss_legacy_top_url: form.rss_legacy_top_url,
    rss_legacy_genre_url: form.rss_legacy_genre_url,
    legacy_top_chart_types: form.legacy_top_chart_types,
    scan_limit_min: form.scan_limit_min,
    scan_limit_max: form.scan_limit_max,
    default_scan_limit: form.default_scan_limit,
    default_scan_enrich: form.default_scan_enrich,
    default_charts: form.default_charts,
    scan_concurrency: form.scan_concurrency,
    scan_max_concurrency: form.scan_max_concurrency,
    analyze_batch_size: form.analyze_batch_size,
    analyze_concurrency: form.analyze_concurrency,
    analyze_max_snapshots: form.analyze_max_snapshots,
    cursor_launch_stagger_ms: form.cursor_launch_stagger_ms,
    cursor_launch_jitter_ms: form.cursor_launch_jitter_ms,
    cursor_chat_timeout_sec: form.cursor_chat_timeout_sec,
    cursor_chat_idle_timeout_sec: form.cursor_chat_idle_timeout_sec,
    pipeline_resume_stale_minutes: form.pipeline_resume_stale_minutes,
    review_mode: form.review_mode,
    http_proxy: form.http_proxy,
    serper_api_key: form.serper_api_key || '',
    workspace: form.workspace,
    host: form.host,
    port: form.port,
    cursor_cwd: form.cursor_cwd || null,
    default_region_preset: form.default_region_preset,
    popular_genre_ids: [...form.popular_genre_ids],
    region_presets,
    store_regions: form.store_regions.map((r) => ({
      code: r.code.trim().toLowerCase(),
      name: r.name.trim(),
      name_zh: r.name_zh.trim(),
    })),
    genres: form.genres.map((g) => ({
      id: Number(g.id),
      name: g.name.trim(),
      name_zh: g.name_zh.trim(),
      search_term: g.search_term.trim(),
    })),
  }
}

async function load() {
  loading.value = true
  try {
    applyData(await api.getSettings())
  } catch (e) {
    message.error(e.message || '加载设置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const data = await api.updateSettings(buildPayload())
    applyData(data)
    message.success('设置已保存并热更新')
    emit('saved', data)
  } catch (e) {
    message.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function reloadFromDisk() {
  loading.value = true
  try {
    applyData(await api.reloadSettings())
    message.success('已从配置文件重新加载')
  } catch (e) {
    message.error(e.message || '重载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="settings-page">
    <div class="settings-head">
      <div>
        <h2 class="settings-title">系统设置</h2>
        <p class="settings-sub">唯一配置源：workspace/settings.json（热更新）。.env 仅在首次生成 settings 或 Key 为测试占位时用于导入。</p>
      </div>
      <n-space>
        <n-button quaternary @click="emit('back')">返回</n-button>
        <n-button :loading="loading" @click="reloadFromDisk">重新加载</n-button>
        <n-button type="primary" :loading="saving" @click="save">保存</n-button>
      </n-space>
    </div>

    <n-alert type="info" :bordered="false" size="small" style="margin-bottom: 12px">
      LLM 按下方列表顺序尝试；某一 provider 失败会自动切换下一个。
      全部失败且非 Mock 模式时，流水线/扫描分析会报错而非静默使用假数据。
      API Key 留空表示不修改已保存的值。
    </n-alert>

    <n-collapse class="settings-collapse" default-expanded-names="general llm scan regions">
      <n-collapse-item title="常规" name="general">
        <n-form label-placement="left" label-width="160" label-align="left">
          <n-form-item label="一键通过（默认）">
            <n-switch v-model:value="form.auto_review_default" />
          </n-form-item>
          <n-form-item label="Review 模式">
            <AdaptiveSelect v-model:value="form.review_mode" :options="reviewModeOptions" style="width: 220px" />
          </n-form-item>
          <n-form-item label="默认区域预设">
            <AdaptiveSelect
              v-model:value="form.default_region_preset"
              :options="regionPresetOptions"
              modal-title="默认区域预设"
              style="width: 220px"
            />
          </n-form-item>
        </n-form>
      </n-collapse-item>

      <n-collapse-item title="LLM 提供商链" name="llm">
        <n-form label-placement="left" label-width="160" label-align="left">
          <n-form-item label="模式">
            <AdaptiveSelect v-model:value="form.llm_provider_mode" :options="modeOptions" style="width: 220px" />
          </n-form-item>
        </n-form>
        <n-dynamic-input v-model:value="form.llm_providers" :on-create="newProvider">
          <template #default="{ value }">
            <n-space vertical style="width: 100%">
              <n-space>
                <AdaptiveSelect v-model:value="value.provider" :options="providerOptions" style="width: 160px" />
                <n-input
                  v-model:value="value.model"
                  :placeholder="value.provider === 'cursor' ? 'composer-2.5' : 'gpt-4o-mini'"
                  style="width: 200px"
                />
              </n-space>
              <n-input
                v-model:value="value.api_key"
                type="password"
                show-password-on="click"
                :placeholder="value._set ? `已配置 ${value._preview}` : 'API Key'"
              />
              <n-input
                v-if="value.provider === 'openai'"
                v-model:value="value.base_url"
                placeholder="OpenAI Base URL"
              />
            </n-space>
          </template>
        </n-dynamic-input>
      </n-collapse-item>

      <n-collapse-item title="App Store RSS" name="rss">
        <n-form label-placement="top" label-align="left">
          <n-form-item label="新版 Marketing RSS">
            <n-input v-model:value="form.rss_marketing_url" type="textarea" :rows="2" />
          </n-form-item>
          <n-form-item label="旧版总榜 RSS">
            <n-input v-model:value="form.rss_legacy_top_url" type="textarea" :rows="2" />
          </n-form-item>
          <n-form-item label="旧版品类 RSS">
            <n-input v-model:value="form.rss_legacy_genre_url" type="textarea" :rows="2" />
          </n-form-item>
          <n-form-item label="走旧版 RSS 的总榜类型">
            <n-dynamic-input v-model:value="form.legacy_top_chart_types" placeholder="如 top-grossing" />
          </n-form-item>
        </n-form>
      </n-collapse-item>

      <n-collapse-item title="扫描与并发" name="scan">
        <n-form label-placement="left" label-width="160" label-align="left">
          <n-form-item label="每类条数下限">
            <n-input-number v-model:value="form.scan_limit_min" :min="1" :max="form.scan_limit_max" />
          </n-form-item>
          <n-form-item label="每类条数上限">
            <n-input-number v-model:value="form.scan_limit_max" :min="form.scan_limit_min" :max="200" />
          </n-form-item>
          <n-form-item label="默认每类条数">
            <n-input-number v-model:value="form.default_scan_limit" :min="form.scan_limit_min" :max="form.scan_limit_max" />
          </n-form-item>
          <n-form-item label="默认 enrich 数">
            <n-input-number v-model:value="form.default_scan_enrich" :min="0" :max="20" />
          </n-form-item>
          <n-form-item label="默认榜单">
            <n-dynamic-input v-model:value="form.default_charts" placeholder="top-free" />
          </n-form-item>
          <n-divider />
          <n-form-item label="榜单拉取并发">
            <n-input-number v-model:value="form.scan_concurrency" :min="1" :max="form.scan_max_concurrency" />
          </n-form-item>
          <n-form-item label="拉取并发上限">
            <n-input-number v-model:value="form.scan_max_concurrency" :min="form.scan_concurrency" :max="50" />
          </n-form-item>
          <n-form-item label="LLM 分析并发批">
            <n-input-number v-model:value="form.analyze_concurrency" :min="1" :max="10" />
          </n-form-item>
          <n-form-item label="LLM 每批快照数">
            <n-input-number v-model:value="form.analyze_batch_size" :min="1" :max="20" />
          </n-form-item>
          <n-form-item label="LLM 分析采样上限">
            <n-input-number
              v-model:value="form.analyze_max_snapshots"
              :min="form.analyze_max_snapshots_min"
              :max="form.analyze_max_snapshots_max"
            />
            <p class="field-hint">
              范围 {{ form.analyze_max_snapshots_min }}–{{ form.analyze_max_snapshots_max }}（默认 40）。
              每个快照约 500–700 token；上限 {{ form.analyze_max_snapshots_max }} 约
              {{ Math.ceil(form.analyze_max_snapshots_max / (form.analyze_batch_size || 6)) }} 批 LLM 调用。
            </p>
          </n-form-item>
          <n-form-item label="Cursor 启动间隔 ms">
            <n-input-number v-model:value="form.cursor_launch_stagger_ms" :min="0" :max="30000" :step="100" />
          </n-form-item>
          <n-form-item label="Cursor 随机抖动 ms">
            <n-input-number v-model:value="form.cursor_launch_jitter_ms" :min="0" :max="5000" :step="50" />
          </n-form-item>
          <n-form-item label="Cursor LLM 总时长上限（秒）">
            <n-input-number
              v-model:value="form.cursor_chat_timeout_sec"
              :min="form.cursor_chat_timeout_sec_min"
              :max="form.cursor_chat_timeout_sec_max"
              :step="60"
            />
            <p class="field-hint">
              单次 Cursor CLI 调用最长运行时间（默认 600s）。
              范围 {{ form.cursor_chat_timeout_sec_min }}–{{ form.cursor_chat_timeout_sec_max }}。
              DevCode 已拆小批次并流式输出；仅在极端慢任务时需调大。
            </p>
          </n-form-item>
          <n-form-item label="Cursor LLM 无输出超时（秒）">
            <n-input-number
              v-model:value="form.cursor_chat_idle_timeout_sec"
              :min="form.cursor_chat_idle_timeout_sec_min"
              :max="form.cursor_chat_idle_timeout_sec_max"
              :step="15"
            />
            <p class="field-hint">
              流式模式下连续无 token 超过该时间则判定卡住（默认 120s）。
              范围 {{ form.cursor_chat_idle_timeout_sec_min }}–{{ form.cursor_chat_idle_timeout_sec_max }}。
            </p>
          </n-form-item>
          <n-form-item label="流水线恢复 stale 分钟">
            <n-input-number
              v-model:value="form.pipeline_resume_stale_minutes"
              :min="form.pipeline_resume_stale_minutes_min"
              :max="form.pipeline_resume_stale_minutes_max"
            />
            <p class="field-hint">
              当前阶段无活动超过该时间才显示「恢复执行」（默认 8 分钟）。
              范围 {{ form.pipeline_resume_stale_minutes_min }}–{{ form.pipeline_resume_stale_minutes_max }}。
            </p>
          </n-form-item>
        </n-form>
      </n-collapse-item>

      <n-collapse-item title="区域与品类" name="regions">
        <p class="section-hint">以结构化条目编辑，保存时由系统自动组装配置，无需手写 JSON。</p>

        <div class="catalog-block">
          <div class="catalog-title">店面国家</div>
          <p class="catalog-desc">App Store 国家/区域代码，每行一个国家。</p>
          <div class="catalog-head-row">
            <div class="catalog-row catalog-row--region catalog-head" aria-hidden="true">
              <span class="field-code">代码</span>
              <span class="field-name">英文名</span>
              <span class="field-zh">中文名</span>
            </div>
            <div class="catalog-head-spacer" aria-hidden="true" />
          </div>
          <n-dynamic-input v-model:value="form.store_regions" :on-create="newStoreRegion">
            <template #default="{ value }">
              <div class="catalog-row catalog-row--region">
                <n-input v-model:value="value.code" placeholder="代码 us" class="field-code" />
                <n-input v-model:value="value.name" placeholder="英文名 United States" class="field-name" />
                <n-input v-model:value="value.name_zh" placeholder="中文名 美国" class="field-zh" />
              </div>
            </template>
          </n-dynamic-input>
        </div>

        <div class="catalog-block">
          <div class="catalog-title">区域预设</div>
          <p class="catalog-desc">扫描页「区域」下拉使用的组合，如 us-eu = 美国 + 欧洲各国。</p>
          <n-dynamic-input v-model:value="form.region_presets" :on-create="newRegionPreset">
            <template #default="{ value }">
              <div class="preset-row">
                <n-input v-model:value="value.key" placeholder="预设名 us-eu" class="field-preset-key" />
                <AdaptiveSelect
                  v-model:value="value.codes"
                  :options="storeRegionSelectOptions"
                  multiple
                  filterable
                  placeholder="选择包含的国家"
                  modal-title="选择包含的国家"
                  class="field-preset-codes"
                  max-tag-count="responsive"
                />
              </div>
            </template>
          </n-dynamic-input>
        </div>

        <div class="catalog-block">
          <div class="catalog-title">App 品类</div>
          <p class="catalog-desc">App Store 一级分类，每行一个品类。</p>
          <div class="catalog-head-row">
            <div class="catalog-row catalog-row--genre catalog-head" aria-hidden="true">
              <span class="field-id">ID</span>
              <span class="field-name">英文名</span>
              <span class="field-zh">中文名</span>
              <span class="field-term">搜索词</span>
            </div>
            <div class="catalog-head-spacer" aria-hidden="true" />
          </div>
          <n-dynamic-input v-model:value="form.genres" :on-create="newGenre">
            <template #default="{ value }">
              <div class="catalog-row catalog-row--genre">
                <n-input-number v-model:value="value.id" placeholder="6013" class="field-id" :show-button="false" />
                <n-input v-model:value="value.name" placeholder="Health & Fitness" class="field-name" />
                <n-input v-model:value="value.name_zh" placeholder="健康健美" class="field-zh" />
                <n-input v-model:value="value.search_term" placeholder="health fitness" class="field-term" />
              </div>
            </template>
          </n-dynamic-input>
        </div>

        <n-form label-placement="top" label-align="left" style="margin-top: 16px">
          <n-form-item label="热门品类（扫描页快捷勾选）">
            <AdaptiveSelect
              v-model:value="form.popular_genre_ids"
              :options="genreSelectOptions"
              multiple
              filterable
              placeholder="从上方品类列表中选择"
              modal-title="热门品类"
              max-tag-count="responsive"
              style="width: 100%"
            />
          </n-form-item>
        </n-form>
      </n-collapse-item>

      <n-collapse-item title="其他" name="other">
        <n-form label-placement="left" label-width="160" label-align="left">
          <n-form-item label="HTTP 代理">
            <n-input v-model:value="form.http_proxy" placeholder="http://127.0.0.1:7890" />
          </n-form-item>
          <n-form-item label="Serper API Key">
            <n-input
              v-model:value="form.serper_api_key"
              type="password"
              show-password-on="click"
              :placeholder="form._serper_set ? `已配置 ${form._serper_preview}` : '可选'"
            />
          </n-form-item>
          <n-form-item label="工作区">
            <n-input v-model:value="form.workspace" />
          </n-form-item>
          <n-form-item label="服务 Host">
            <n-input v-model:value="form.host" />
          </n-form-item>
          <n-form-item label="服务 Port">
            <n-input-number v-model:value="form.port" :min="1" :max="65535" />
          </n-form-item>
          <n-form-item label="Cursor CWD">
            <n-input v-model:value="form.cursor_cwd" placeholder="留空使用项目根目录" />
          </n-form-item>
        </n-form>
      </n-collapse-item>
    </n-collapse>
  </div>
</template>

<style scoped>
.settings-page {
  width: 100%;
  max-width: 960px;
  padding-bottom: 48px;
}

.settings-collapse :deep(.n-collapse-item__content-inner) {
  padding-left: 22px;
  box-sizing: border-box;
}

.settings-collapse :deep(.n-form),
.settings-collapse :deep(.n-dynamic-input) {
  width: 100%;
  max-width: 100%;
}

.settings-collapse :deep(.n-form-item .n-form-item-blank) {
  justify-content: flex-start;
  align-items: flex-start;
}

.settings-collapse :deep(.n-form-item-label) {
  text-align: left;
}

.settings-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.settings-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.settings-sub {
  margin: 4px 0 0;
  font-size: 13px;
  opacity: 0.55;
}

.section-hint {
  margin: 0 0 16px;
  font-size: 13px;
  opacity: 0.6;
  line-height: 1.5;
  text-align: left;
}

.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  opacity: 0.55;
  line-height: 1.45;
  text-align: left;
}

.catalog-title,
.catalog-desc {
  text-align: left;
}

.catalog-block {
  margin-bottom: 24px;
  width: 100%;
}

.catalog-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.catalog-desc {
  margin: 0 0 10px;
  font-size: 12px;
  opacity: 0.5;
}

.catalog-head-row {
  display: flex;
  align-items: center;
  margin-bottom: 6px;
}

.catalog-head-row .catalog-row {
  flex: 1;
  min-width: 0;
  margin-bottom: 0;
}

.catalog-head-spacer {
  flex-shrink: 0;
  width: 68px;
  margin-left: 20px;
}

.catalog-head {
  padding: 0;
  font-size: 11px;
  opacity: 0.45;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.catalog-row {
  display: grid;
  gap: 8px;
  width: 100%;
  align-items: center;
}

.catalog-row--region {
  grid-template-columns: 100px 1fr 120px;
}

.catalog-row--genre {
  grid-template-columns: 88px 1fr 1fr 1fr;
}

.preset-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 8px;
  width: 100%;
  align-items: center;
}

.field-id {
  width: 100%;
}

@media (max-width: 720px) {
  .catalog-row {
    grid-template-columns: 1fr 1fr;
  }

  .catalog-row .field-id {
    grid-column: 1 / -1;
  }

  .preset-row {
    grid-template-columns: 1fr;
  }
}
</style>
