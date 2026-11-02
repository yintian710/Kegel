<script setup lang="ts">
import AppLayout from './layouts/AppLayout.vue'
</script>

<template>
  <NConfigProvider>
    <NMessageProvider>
      <NDialogProvider>
        <AppLayout>
          <RouterView v-slot="{ Component }">
            <component :is="Component" />
          </RouterView>
        </AppLayout>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
