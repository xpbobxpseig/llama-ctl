<script setup>
/**
 * 市场工具行：热门榜标题 + 源切换 + 搜索（400ms 防抖）+ 量级下拉 + 刷新。
 * 数据与动作全部走 market store，本组件不持业务状态。
 */
import { computed, ref } from 'vue'
import * as store from '../../stores/snapshot.js'
import * as market from '../../stores/market.js'
import { t } from '../copy.js'
import Dd from '../Dd.vue'

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

const hubOptions = [
  { value: 'ms', label: '魔搭 ModelScope' },
  { value: 'hf', label: 'HuggingFace' },
]

/** 量级档位：0=全部。默认 ≥1B（spec 工单 3），档位给足往上选的空间。 */
const minOptions = computed(() => [
  { value: '0', label: tr('allSizes') },
  { value: '1', label: '≥1B' },
  { value: '7', label: '≥7B' },
  { value: '30', label: '≥30B' },
])

const search = ref('')
let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => market.setQuery(search.value), 400)
}
</script>

<template>
  <div class="section market-head">
    <span>{{ tr('hot') }}</span>
    <Dd
      class="hubdd"
      :options="hubOptions"
      :model-value="market.hub.value"
      @change="market.saveHub($event)"
    />
    <input
      v-model="search"
      class="nameinput search"
      type="text"
      spellcheck="false"
      :placeholder="tr('searchPh')"
      @input="onSearch"
    />
    <span class="mlabel">{{ tr('scaleLabel') }}</span>
    <Dd
      class="mindd"
      :options="minOptions"
      :model-value="String(market.minB.value)"
      @change="market.setMinB($event)"
    />
    <button class="textbtn" type="button" :disabled="store.busy.value" @click="market.loadList()">{{ tr('refresh') }}</button>
  </div>
</template>
