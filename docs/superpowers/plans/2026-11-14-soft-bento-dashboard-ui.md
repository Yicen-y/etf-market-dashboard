# Soft Bento Dashboard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有数据和金融计算的前提下，以方案A逐页统一A股ETF看板的视觉、导航、响应式和状态反馈。

**Architecture:** 以 `web/theme.css` 定义设计令牌，`web/ui-components.css` 提供共享外壳、导航、卡片、工具栏和状态样式；各页面CSS只保留业务布局。现有HTML、JavaScript和FastAPI接口保持原有边界。

**Tech Stack:** HTML、CSS、原生JavaScript、ECharts、FastAPI、pytest。

## Global Constraints

- 不修改金融计算公式、数据源与 API 路径。
- 保留中国市场红涨绿跌语义。
- 保持桌面与移动端响应式。
- 所有新交互具备键盘焦点和可访问名称。
- 保留现有页面路由与数据刷新逻辑。

---

### Task 1: 全局设计令牌和共享卡片

**Files:**
- Modify: `web/theme.css`
- Modify: `web/ui-components.css`
- Test: `tests/test_soft_bento_ui.py`

**Interfaces:**
- Produces: CSS变量 `--surface-soft`、`--surface-raised`、`--radius-card`、`--radius-control`、`--shadow-card`、`--shadow-raised`。

- [ ] **Step 1: 编写失败测试**

断言新设计令牌、44px触控高度、16px卡片圆角和移动端断点存在。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_soft_bento_ui.py -q`  
Expected: FAIL，缺少新令牌。

- [ ] **Step 3: 实现主题与共享组件**

更新主题变量、卡片层级、按钮、输入框、状态条、表格和响应式规则。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_soft_bento_ui.py tests/test_ui_foundation.py tests/test_responsive_ui.py -q`  
Expected: PASS。

### Task 2: 导航与页面外壳

**Files:**
- Modify: `web/navigation.js`
- Modify: `web/ui-components.css`
- Test: `tests/test_soft_bento_ui.py`
- Test: `tests/test_ui_foundation.py`

**Interfaces:**
- Consumes: Task 1设计令牌。
- Produces: 分组导航、唯一激活状态、移动端抽屉和底部快捷入口样式。

- [ ] **Step 1: 添加导航结构失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 最小化调整导航标记与CSS**
- [ ] **Step 4: 运行导航与响应式测试**

### Task 3: ETF轮动与三棱镜首批改造

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`
- Modify: `web/app.js`
- Test: `tests/test_prism_ui.py`
- Test: `tests/test_rotation_overview.py`
- Test: `tests/test_soft_bento_ui.py`

**Interfaces:**
- Consumes: 共享卡片、工具栏、状态与导航。
- Produces: Bento KPI、紧凑工具栏、图表卡片、三棱镜统一页面层级。

- [ ] **Step 1: 添加页面结构失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 调整HTML类名与页面CSS**
- [ ] **Step 4: 保持图表行为并运行回归测试**

### Task 4: 股息率监测页面

**Files:**
- Modify: `web/dividend.html`
- Modify: `web/dividend.css`
- Modify: `web/dividend.js`
- Test: `tests/test_dividend_research_ui.py`
- Test: `tests/test_soft_bento_ui.py`

**Interfaces:**
- Produces: 搜索、自选列表、Wind股息率、数据状态和详情卡片的统一视觉。

- [ ] **Step 1: 添加股息率页面失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现卡片化布局和移动端展示**
- [ ] **Step 4: 运行股息率与可访问性测试**

### Task 5: 资金流向、五年之锚和研究页面

**Files:**
- Modify: `web/fund-flow.css`
- Modify: `web/anchor.css`
- Modify: `web/dividend-research.css`
- Modify: `web/bond-value.css`
- Test: `tests/test_fund_flow_ui.py`
- Test: `tests/test_responsive_ui.py`

**Interfaces:**
- Consumes: 共享视觉令牌。
- Produces: 页面间一致的卡片、工具栏、图表标题和状态反馈。

- [ ] **Step 1: 添加页面一致性失败测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 应用共享视觉层**
- [ ] **Step 4: 运行页面回归测试**

### Task 6: 浏览器验收

**Files:**
- Test: `tests/ui_live_smoke_v2.py`

- [ ] **Step 1: 启动本地服务**
- [ ] **Step 2: 验证375、768、1024、1440宽度**
- [ ] **Step 3: 验证导航唯一高亮、键盘焦点、图表尺寸和数据状态**
- [ ] **Step 4: 运行完整相关测试并记录结果**

