# 前端风格记录

## TDesign 组件库约定

本项目使用 `tdesign-vue-next`（Vue 3 版本，v1.12+），全局注册，不做按需引入。

### 集成方式

```js
// main.js
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
app.use(TDesign)
```

- 所有 `t-*` 组件无需单独 import，直接在模板中使用
- 只有编程式 API 需要手动引入，例如 `import { MessagePlugin } from 'tdesign-vue-next'`

### 主题与深色模式

项目使用自定义 `useTheme` composable 控制深/浅色，不是用 TDesign 内置的暗色主题切换。

- 根组件用 `<t-config-provider :global-config="globalConfig">` 包裹
- CSS 变量混用两套：
  - TDesign token：`var(--td-bg-color-page)`、`var(--td-text-color-primary)`、`var(--td-component-stroke)`、`var(--td-shadow-1)`、`var(--td-brand-color)` 等，均带硬编码 fallback
  - 自定义 surface token：`--surface-text-primary`、`--surface-shell-bg` 等，在组件 scoped style 里按主题覆写
- 深色模式通过根节点 class `is-dark-theme` 切换 CSS 变量值
- 组件内部样式用 `:deep()` 选择器覆盖 TDesign 内部 DOM，例如：
  ```css
  :deep(.t-tabs__nav-item) { ... }
  :deep(.t-tabs__bar) { ... }
  ```

### 常用组件与使用规范

| 场景 | 组件 | 注意事项 |
|---|---|---|
| 布局网格 | `t-row` / `t-col` | 用响应式断点 `:xs` `:sm` `:md` `:lg` |
| 标签页导航 | `t-tabs` / `t-tab-panel` | `v-model` 绑定当前值，`:destroy-on-hide="false"` 保持面板状态 |
| 数据表格 | `t-table` | 通过 `#slot` 自定义列渲染；`size="small"` 适配紧凑场景 |
| 按钮 | `t-button` | `theme` 区分语义（primary/danger），`variant="outline"` 做次要操作，`size="small"` 用于紧凑区域 |
| 开关 | `t-switch` | `size="large"` 用于配置项，`size="small"` 用于顶栏等轻量场景 |
| 下拉选择 | `t-select` / `t-option` | 选项用 `:options` 数组传入，或 `<t-option>` 子元素；`multiple` + `filterable` 用于多选搜索 |
| 数字输入 | `t-input-number` | 配合 `:min` `:max` `:step` 限制范围 |
| 弹窗 | `t-dialog` | `v-model:visible` 控制显隐；`:footer="false"` 自定义底部按钮 |
| 提示消息 | `MessagePlugin` | `MessagePlugin.success()` / `.error()` 全局提示，无需挂载 DOM |
| 标签 | `t-tag` | `theme` 控制颜色（success/warning/danger），`variant="light"` 浅色底 |
| 文本域 | `t-textarea` | `:autosize="false"` 手动控制高度，配合 scoped style 覆写内部 DOM |
| 进度条 | `t-progress` | `status` 控制颜色（success/warning），`size="small"` 紧凑显示 |
| 折叠面板 | `t-collapse` / `t-collapse-panel` | 用于可展开的详情区域 |
| 加载 | `t-loading` | 可作独立组件或指令使用 |

### Props 使用模式

组件样式优先通过 props 控制，而非自定义 CSS：

- 语义颜色：`theme="success"` / `theme="warning"` / `theme="danger"`
- 视觉变体：`variant="light"` / `variant="outline"`
- 尺寸：`size="small"` / `size="large"`
- 形状：`shape="round"` / `shape="circle"`
- 边框：`:bordered="false"` 去掉边框
- loading 状态：`:loading="saving"` 按钮自带 loading 动画

### Switch 特别说明

`t-switch` 的 `label` 数组顺序是：

- `label[0]` = 开启时显示
- `label[1]` = 关闭时显示

因此像"C段扫描"这种开关，如果要显示中文文案，应写成：

```vue
<t-switch v-model="scanCfg.enable_c_scan" :label="['开启', '关闭']" />
```

不要写反，否则会出现"灰色但显示开启"的错位。

---

## 参数面板风格

这份风格用于后台里的“系统配置 / 扫描配置”这类设置型页面。

参考实现：

- `frontend/src/components/SettingsTab.vue`
- `frontend/src/components/ScanConfigTab.vue`

### 适用场景

- 参数配置页
- 扫描配置页
- 需要把很多表单项分组展示的后台页面
- 有“状态摘要 + 分组面板 + 底部操作区”的管理界面

### 视觉方向

- 整体是“浅色浮层卡片”风格，不要做成普通长表单
- 外层卡片带轻微渐变和很淡的径向高光
- 面板内部继续分组，用 2 列卡片承载
- 卡片圆角偏大，阴影轻，不要厚重
- 标题层级清楚，说明文字短而准
- 顶部用 pill/tag 做摘要状态，不要只堆表单

### 布局规则

1. 页面主卡片结构：
   - 顶部：标题 + 一句说明 + 右侧状态 pill
   - 中部：2 列 panel grid
   - 底部：操作提示 + 保存/重载按钮

2. 每个 panel 结构：
   - eyebrow 小标题
   - h3 主标题
   - 1 段说明文字
   - 若干 config-field

3. 每个 field 结构：
   - 左侧：字段名 + 一句解释
   - 右侧：短控件，不要整行拉满
   - 特殊内容（多选、省份、定时、switch）可以用 stack 结构纵向排

4. 响应式：
   - 桌面端 2 列
   - 窄屏降成 1 列
   - 小屏时 field 改成纵向堆叠

### 控件规则

- `InputNumber` 默认用固定较短宽度，例如 `220px`
- `Select / Input` 稍宽，例如 `280px ~ 320px`
- 复杂块（省份选择、定时设置、switch 说明）放在内层小卡片里
- 开关旁边必须给出明确状态文案，不要只靠颜色判断

### 文案规则

- 字段说明用“为什么改它 / 改了会怎样”的句式
- 每个分组说明控制在 1 句
- 底部操作提示写“保存后影响什么”
- 尽量让用户一眼知道当前状态，例如：
  - `当前模式：单次执行`
  - `C段扫描：已关闭`
  - `范围：全国`

### 配色与可读性

- 即使页面处于深色模式，这类浅色参数卡片上的文字也要用显式深色值
- 不要完全依赖主题变量自动继承，否则容易出现“浅底 + 浅字”
- 当前这套推荐：
  - 主文字：`#0f172a`
  - 次级文字：`#475569` / `#64748b`
  - 强调蓝：`#2563eb`
  - 强调绿：`#047857`

### 样式关键词

如果以后要让我继续按这个风格改，可以直接说这些关键词：

- “按参数面板风格改”
- “按 `docs/frontend-style-guide.md` 的设置页风格改”
- “做成双列分组卡片，不要长表单”
- “要有顶部摘要 pill、面板说明、底部操作区”

### 组件实现约定

- 优先复用这些 class 命名思路：
  - `config-card`
  - `config-header`
  - `config-header-pills`
  - `config-panel-grid`
  - `config-panel`
  - `config-field`
  - `config-field-meta`
  - `field-control`
  - `config-actions`

这样后续页面更容易保持同一套视觉语言。

### 以后如果要进一步固化

如果后面这种页面会越来越多，下一步建议做二选一：

1. 抽公共样式
   - 把这套 `config-*` class 提到公共样式文件

2. 抽公共组件
   - 例如做 `ConfigPageCard`、`ConfigPanel`、`ConfigField` 这类基础组件

前者改动小，后者复用更彻底。
