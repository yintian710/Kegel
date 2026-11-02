<script setup lang="ts">
import PreferencesPanel from '../components/PreferencesPanel.vue'
import SiteNavigation from '../components/SiteNavigation.vue'
</script>

<template>
  <SiteNavigation />
  <slot />
  <PreferencesPanel />
</template>
