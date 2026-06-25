<script setup>
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme } from 'naive-ui'
import { themeOverrides } from './theme'
import AppContent from './AppContent.vue'
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <AppContent />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
