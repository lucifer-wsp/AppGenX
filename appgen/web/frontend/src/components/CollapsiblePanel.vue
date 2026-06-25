<script setup>
const props = defineProps({
  title: { type: String, required: true },
  collapsed: { type: Boolean, default: false },
  fill: { type: Boolean, default: false },
})

const emit = defineEmits(['update:collapsed'])

function toggle() {
  emit('update:collapsed', !props.collapsed)
}
</script>

<template>
  <section class="collapsible-panel" :class="{ 'is-collapsed': collapsed, 'fill-height': fill && !collapsed }">
    <header class="panel-header" @click="toggle">
      <span class="panel-title">{{ title }}</span>
      <div v-if="$slots['header-extra']" class="panel-extra" @click.stop>
        <slot name="header-extra" />
      </div>
      <button
        type="button"
        class="panel-toggle"
        :aria-label="collapsed ? '展开' : '折叠'"
        :title="collapsed ? '展开' : '折叠'"
        @click.stop="toggle"
      >
        <svg
          v-if="collapsed"
          class="panel-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
        <svg
          v-else
          class="panel-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <polyline points="18 15 12 9 6 15" />
        </svg>
      </button>
    </header>
    <div v-show="!collapsed" class="panel-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.collapsible-panel {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.15s ease;
}

.collapsible-panel.is-collapsed {
  flex-shrink: 0;
}

.panel-header {
  height: 44px;
  min-height: 44px;
  padding: 0 12px 0 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid transparent;
  transition: background 0.15s ease;
}

.collapsible-panel:not(.is-collapsed) .panel-header {
  border-bottom-color: rgba(255, 255, 255, 0.06);
}

.panel-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-extra {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.panel-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease, color 0.15s ease;
}

.panel-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.85);
}

.panel-icon {
  width: 16px;
  height: 16px;
}

.panel-body {
  padding: 14px 16px 16px;
}

.collapsible-panel.fill-height {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.collapsible-panel.fill-height .panel-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
