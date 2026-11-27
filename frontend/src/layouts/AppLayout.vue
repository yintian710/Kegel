<script setup lang="ts">
import PreferencesPanel from '../components/PreferencesPanel.vue'
import SiteNavigation from '../components/SiteNavigation.vue'
</script>

<template>
  <SiteNavigation />
  <div class="app-main-layout">
    <slot />
  </div>
  <PreferencesPanel />
</template>

<style scoped>
.app-main-layout {
  padding-top: 60px;
  min-height: 100vh;
  min-height: 100svh;
  box-sizing: border-box;
}
</style>
