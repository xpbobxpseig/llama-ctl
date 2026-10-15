<script setup>
/**
 * The console view: status card, then the slots tickets 13-17 fill.
 *
 * It is the shell's default destination and the screen that proves the Snapshot
 * round trip. The parameter form (13) and the log tail (14) drop into the slots
 * below without touching this file.
 */
import StatusCard from '../components/StatusCard.vue'
import ParamForm from '../components/ParamForm.vue'
import LogTail from '../components/LogTail.vue'
</script>

<template>
  <div class="view">
    <StatusCard />

    <!-- Ticket 13: the seven collapsible parameter groups. -->
    <div class="slot enter enter-2">
      <slot name="form">
        <ParamForm />
      </slot>
    </div>

    <!-- Ticket 14: the server.err log tail. -->
    <div class="slot enter enter-3">
      <slot name="log">
        <LogTail />
      </slot>
    </div>
  </div>
</template>

<style scoped>
.view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
  min-width: 0;
}

.slot {
  min-width: 0;
}
</style>
