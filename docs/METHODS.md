# 方法、公式与验证边界

## 1. 预测

日粒度按商品聚合，目标是非负已履约发货量。SES 的平滑参数固定为 0.25；Croston-SBA 固定为 0.1。Croston 用非零需求的大小和间隔分别进行指数平滑，SBA 点预测为 `(1 - alpha/2) * size / interval`；首个间隔采用历史起点到首次非零需求的长度。全零序列预测为零；长期无需求后该方法不自动衰减，这是已知局限。

星期结构融合：过去 28 日同一星期位置的均值乘以近期 7 日均值与 28 日均值之比，比例限制在 `[0.5, 1.5]`；与近期均值按 `0.7/0.3` 融合。系数均为事先指定的演示规则，不从测试期优化。

在测试开始前 42 天按 7 日非重叠窗口累计绝对误差，为每个商品选择一个方法，平局按固定方法顺序处理。测试前若不足 56 天训练历史则拒绝运行。最终 56 天共有 8 个预测时点，起点前的数据可用于更新参数。选模不看到最终测试实际值。

```text
WAPE = sum(|actual - forecast|) / sum(actual)
Bias = (sum(forecast) - sum(actual)) / sum(actual)
MAE  = mean(|actual - forecast|)
MASE = mean(|actual - forecast| / mean_training(|y[t] - y[t-7]|))
```

WAPE 分母为零时未定义；MASE 的季节差分标度在每个预测时点仅由训练历史计算，标度为零时不计入 MASE 均值。零需求很多时不使用逐条 MAPE。这里的 WAPE 为整个测试面板的量加权口径，MASE 为有定义样本的算术均值。

选模、分层、商品范围选择均需要防止使用未来信息。公开生成器的商品集合事先确定；私有数据规范化时需把商品范围选择冻结在验证期之前，并记录样本筛选规则，避免依据测试期高销量挑商品。

## 2. 分层与补货

ABC 按测试前 `累计发货量 × 情景单位成本` 降序，累计份额跨越 80% 和 95% 划分。边界采用“加入当前商品前”的累计比例，避免第一个大商品直接跳出 A 类。XYZ 使用每日数量总体标准差与均值之比：`CV <= 0.5` 为 X，`0.5 < CV <= 1` 为 Y，其他为 Z。阈值是演示约定，并非行业统一标准。

每 7 天复核，假设提前期 L 为固定整数天。保护期为 `L+7`。三个策略：

| 策略 | 订货后目标库存位置 S |
|---|---|
| uniform_95 | `mean_28 * (L+7) + z_0.95 * std_56 * sqrt(L+7)` |
| segmented_forecast | `sum(selected point forecast for L+7) + z_ABC * std_56 * sqrt(L+7)` |
| fixed_cover | `mean_28 * (L+7+7)` |

A/B/C 的 z 对应名义分位数 98%/95%/90%。标准差采用过去 56 日原始数量，正态与独立日需求是此安全库存近似的假设；自相关、促销或间歇需求会破坏近似。未验证这些假设前，S 不是校准过的概率保证。

```text
inventory_position = on_hand + outstanding_orders
order_qty = ceil(max(0, S - inventory_position) / batch_size) * batch_size
```

事件顺序：日初收货 → 满足当天需求 → 记录未满足量为丢失销售 → 日末复核下单 → L 天后日初到货。日末订单可使用当天已观察的需求，不能使用未来需求。各策略使用相同需求、同一期初库存、同一提前期、批量和成本参数，期初在途均为零。

```text
initial_stock + all_ordered = all_filled + ending_stock + ending_pipeline
fill_rate = total_filled / total_demand
service_cost = sum(end_stock * unit_cost * 0.001) + 5 * order_count
               + shortage_multiplier * sum(lost * unit_cost)
```

敏感性组合：提前期乘数 `[0.7,1.0,1.3]` × 缺货惩罚乘数 `[2,5,10]` × 3 策略。提前期四舍五入且至少 1 日。服务成本未包括采购成本、资金现金流与期末残值；不能与财务利润对等。

## 3. 年度首印与报童模型

每个规划商品包含五年已关联的净实销历史。这里的关联商品是版本映射后的规划轨迹，不能当然视作跨年完全相同的物理 SKU。

点预测是两个信号的等权融合：最近一年实销乘以受限增长比例 `[0.7,1.15]`，以及最多最近三年的递增权重均值。增长比例用加一保护零分母。只有第五或更早年度已有结果时，才能进入后续年度的校准池。

在每个评估年之前，对全部商品早期时点计算 `observed / max(predicted,1)`。使用跨商品的比例残差池，再取事先指定的成本比对应的经验分位数：

```text
critical_fractile = shortage_cost / (shortage_cost + overage_cost)
target = point_forecast * empirical_quantile(previous_ratio_residuals, critical_fractile)
print_qty = ceil(target / 50) * 50
loss = overage_cost * max(print_qty - actual, 0)
       + shortage_cost * max(actual - print_qty, 0)
```

成本比固定为 `1:1 / 3:1 / 9:1`，对应 50%/75%/90%。这是将报童成本权衡应用于简化首印问题的启发式：残差可交换、未来结构稳定等假设未获证明，离散批量取整也不保证得到所有离散可行量中的精确最优报童解。

只回测最后两年；前两年训练、第三年可提供第一个先前残差。早期年份和样本数量有限；不同年度结果并不独立，且同年度轨迹存在共同市场冲击。因此不报告显著性或对实际业务的因果归因。过量计划既可能成为库存，也可能被调拨、折价或退货，不能直接等同实际退货量。

## 4. 单周期整数产能分配

这是独立于上面历史首印回测的约束实验，面向全部已知年度历史之后的一期。目标 d 是年度点预测净掉兼容可用库存后的量；公开实验明确设兼容库存为 0。没有拿未知未来实销当排产目标。

```text
variables: b_i >= 0 integer batches, z_i binary setup,
           u_i >= 0 underage, o_i >= 0 overage
minimize: sum(p_i*u_i + h*o_i + k*z_i)
subject to:
  batch*b_i + u_i - o_i = d_i
  minimum_batches*z_i <= b_i <= floor(capacity/batch)*z_i
  sum(batch*b_i) <= capacity
```

演示设批量 50、最少 2 批、换线启用成本 30、过量单位成本 1。缺量优先级由历史数量排序给出，最高 20% 为 9，其次 40% 为 5，其余为 3；这些均是情景成本单位。测试三档总印量产能 50%/75%/100%。

贪心基线按缺量惩罚由高到低，满足同样起印与批量约束，只有边际损失下降时才追加批次。MILP 用 SciPy/HiGHS 求解，要求成功状态并达到相对间隙 `1e-8`；若超时或没有证明最优则报错，不把未证明的可行解称为最优。输出保留状态、目标值、对偶界和间隙；小规模测试与穷举比较最优目标。

总印量容量不是具体印厂的机时。当前不包含多机分配、多期库存、物料清单、纸张约束、供应商交付或顺序相关换版时间，因此应称为“印量产能分配”，不宜表述为完整的 APS 排程系统。
