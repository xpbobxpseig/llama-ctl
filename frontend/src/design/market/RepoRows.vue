<script setup>
/**
 * 市场发现区：列表态（热门榜 / 搜索结果）与详情态（量化档行）互斥渲染。
 * 模板与拆分前逐字一致——DOM 类名被 smoke 契约锁定。
 */
import { computed } from 'vue'
import * as store from '../../stores/snapshot.js'
import * as market from '../../stores/market.js'
import { t } from '../copy.js'
import {
  fmtBytes as fmtBytesFn,
  fmtCount as fmtCountFn,
  taskFor as taskForFn,
  TIER_CLASS,
  TIER_TEXT,
} from '../market-fmt.js'

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

const gb = fmtBytesFn
const fmtCount = fmtCountFn
const tierClass = TIER_CLASS

function fitText(tier) {
  return tr(TIER_TEXT[tier] || 'fitNo')
}

const detailVariants = computed(() => market.detail.value?.variants ?? [])

const taskFor = (repo, label) => taskForFn(market.tasks.value, repo, label)
</script>

<template>
  <!-- 详情 -->
  <template v-if="market.detail.value">
    <div class="mrow back">
      <button class="textbtn" type="button" @click="market.closeDetail()">{{ tr('back') }}</button>
      <span class="nm">{{ market.detail.value.id }}</span>
      <span v-if="market.detail.value.gated" class="fit f-gated">{{ tr('gated') }}</span>
    </div>
    <div class="lrow meta">
      <span class="mono">
        {{ tr('downloads') }} {{ fmtCount(market.detail.value.downloads) }}
        <template v-if="market.detail.value.gguf?.context_length">· {{ tr('ctx') }} {{ market.detail.value.gguf.context_length }}</template>
        <template v-if="market.detail.value.gguf?.architecture">· {{ tr('arch') }} {{ market.detail.value.gguf.architecture }}</template>
        <template v-if="market.detail.value.gguf?.total_params">· {{ (market.detail.value.gguf.total_params / 1e9).toFixed(1) }}B</template>
      </span>
      <span v-if="detailVariants.some((v) => v.mmproj)" class="fl">{{ tr('mmprojHint') }}</span>
    </div>
    <div v-for="v in detailVariants" :key="v.label" class="mrow variant">
      <div class="vmain">
        <span class="nm">{{ v.label }}</span>
        <span v-if="v.is_sharded" class="fl">{{ tr('shards') }} {{ v.files.length }}</span>
        <span class="mono size">{{ gb(v.total_size + (v.mmproj?.size ?? 0)) }}</span>
        <span class="fit" :class="tierClass[v.fit?.tier || 'not_recommended']">{{ fitText(v.fit?.tier) }}</span>
      </div>
      <div class="vfit">
        <span class="why">{{ v.fit?.reason }}</span>
        <button
          class="pillbtn"
          type="button"
          :disabled="!!taskFor(market.detail.value.id, v.label)"
          @click="market.enqueue(v, market.detail.value.id)"
        >
          {{ taskFor(market.detail.value.id, v.label) ? tr('dlQueued') : tr('download') }}
        </button>
      </div>
    </div>
  </template>

  <!-- 列表 -->
  <template v-else>
    <div v-if="!market.list.value.length" class="lrow meta">{{ tr('marketEmpty') }}</div>
    <button v-for="r in market.list.value" :key="r.id" class="mrow repo" type="button" @click="market.openDetail(r.id)">
      <span class="nm">{{ r.name }}</span>
      <span v-if="r.gated" class="fit f-gated">{{ tr('gated') }}</span>
      <span class="mono dim">
        {{ r.params_b ? r.params_b + 'B · ' : '' }}{{ tr('downloads') }} {{ fmtCount(r.downloads) }}
      </span>
    </button>
  </template>
</template>
