<script setup lang="ts">
import { CAT_VALUE, type Grade, type RiskCategory } from '@/domain/riskScore'

const props = defineProps<{
  categories: RiskCategory[]
  g: number | null
  grade: Grade | null
}>()

function sum(categories: RiskCategory[]): number {
  return categories.reduce((acc, cat) => acc + CAT_VALUE[cat], 0)
}
</script>

<template>
  <div class="sec-title">附录A　电梯综合安全状况等级确定方法说明</div>
  <p>在确定每个评价项目风险情节的风险类别后，按如下方法确定综合安全状况等级：</p>
  <p>
    a) 将三种风险类别分别按照表A.1所示规则赋值，假设 v<sub>i</sub> 为对应于第 i
    个风险情节的风险类别取值，其中 n 为进行评价的风险情节的总数。
  </p>
  <p class="ctr">表A.1　风险类别分值</p>
  <table>
    <tbody>
      <tr>
        <th class="ctr">风险类别</th>
        <th class="ctr">Ⅰ</th>
        <th class="ctr">Ⅱ</th>
        <th class="ctr">Ⅲ</th>
      </tr>
      <tr>
        <td class="ctr">值</td>
        <td class="ctr">0</td>
        <td class="ctr">-1</td>
        <td class="ctr">2</td>
      </tr>
    </tbody>
  </table>
  <p class="notes">注：Ⅰ类风险为一票否决项。</p>
  <p>b) 按照以下公式计算综合安全状况得分 G：</p>
  <p class="ctr formula">
    G = 100 × ( Σ<sub>i=1..n</sub> v<sub>i</sub> ) / (2n)　　（∀v<sub>i</sub>≠0）<br />
    G = 0　　（∃v<sub>i</sub>=0，或 Σ<sub>i=1..n</sub> v<sub>i</sub> &lt; 0）
  </p>
  <p v-if="props.g !== null" class="ctr">
    本次计算：n = {{ props.categories.length }}，Σv = {{ sum(props.categories) }}，G = {{ props.g }}
  </p>
  <p v-else>本次尚无有效综合评定，暂不输出综合得分和等级。</p>
  <p>c) 根据得分情况，按照表A.2判断电梯综合安全状况等级</p>
  <p class="ctr">表A.2　电梯综合安全状况等级</p>
  <table>
    <tbody>
      <tr>
        <th class="ctr">G</th>
        <th class="ctr">G≥90</th>
        <th class="ctr">75≤G&lt;90</th>
        <th class="ctr">60≤G&lt;75</th>
        <th class="ctr">G&lt;60</th>
      </tr>
      <tr>
        <td class="ctr">综合安全状况等级</td>
        <td class="ctr">一级</td>
        <td class="ctr">二级</td>
        <td class="ctr">三级</td>
        <td class="ctr">四级</td>
      </tr>
    </tbody>
  </table>
  <p v-if="props.grade !== null">本次判定结果：<b>{{ props.grade }}</b></p>
</template>

<style scoped>
.formula {
  font-family: 'Cambria Math', serif;
}
</style>
