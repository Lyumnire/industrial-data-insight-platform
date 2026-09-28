<!-- AI-assisted -->
<!-- 平台品牌 Logo：六边形（工业制造与数据底座母题）+ 对话尾角（问）+ 数据脉冲线（析）。
     颜色走主题令牌（--app-primary/--app-accent-emerald），明暗主题自动适配；
     渐变 id 按实例生成，避免同页多实例的 SVG id 冲突。 -->
<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 28 })
const uid = `bl-${Math.random().toString(36).slice(2, 9)}`
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    fill="none"
    aria-hidden="true"
    class="brand-logo-mark"
  >
    <defs>
      <linearGradient
        :id="`${uid}-g`"
        x1="6"
        y1="4"
        x2="42"
        y2="44"
        gradientUnits="userSpaceOnUse"
      >
        <stop stop-color="var(--app-primary, #38bdf8)" />
        <stop offset="1" stop-color="var(--app-accent-emerald, #10b981)" />
      </linearGradient>
    </defs>

    <!-- 对话尾角（问）：置于六边形之下，底边与六边形左下边重合 -->
    <path
      d="M17.9 40.2 L4.8 44.6 L9.3 35.4 Z"
      :fill="`url(#${uid}-g)`"
      fill-opacity="0.85"
      :stroke="`url(#${uid}-g)`"
      stroke-width="2.4"
      stroke-linejoin="round"
    />

    <!-- 六边形主体（制造 / 数据底座） -->
    <path
      d="M24 4 L41.3 14 L41.3 34 L24 44 L6.7 34 L6.7 14 Z"
      :fill="`url(#${uid}-g)`"
      fill-opacity="0.08"
      :stroke="`url(#${uid}-g)`"
      stroke-width="3"
      stroke-linejoin="round"
    />

    <!-- 数据脉冲线（析） -->
    <path
      d="M13.5 24.5 H18 L21 18 L25.5 29 L28.5 24.5 H34.5"
      :stroke="`url(#${uid}-g)`"
      stroke-width="2.6"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<style scoped>
.brand-logo-mark {
  display: block;
  flex-shrink: 0;
}
</style>
