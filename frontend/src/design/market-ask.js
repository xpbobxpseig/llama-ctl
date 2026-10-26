/**
 * 市场页行内确认的共享状态（拆分自 MarketView 的四个 ref）。
 *
 * 任务行与已下载行各自持有一个键；打开一处确认时按既有语义关掉另一处的
 * ——拆分前这些 ref 都在 MarketView 里，跨区清空是同一份数据，拆成子组件
 * 后仍必须是同一份，所以落成模块级 reactive 而不是各自的局部状态。
 */
import { reactive } from 'vue'

export const ask = reactive({
  /** 完成任务行内「启用」确认：task id */
  task: '',
  /** 已下载行「启用」确认：model path */
  enable: '',
  /** 已下载行「实测」确认：model path */
  bench: '',
  /** 已下载行「删除」确认：model path */
  del: '',
})
