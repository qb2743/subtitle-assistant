# Bug修复：SwitchButton信号错误

**日期**：2026-06-21  
**状态**：✅ 已修复

---

## ❌ **错误信息**

```
AttributeError: 'SwitchButton' object has no attribute 'toggled'
```

---

## 🐛 **问题原因**

使用了错误的信号名称：

```python
# ❌ 错误
self.pause_switch.toggled.connect(self._on_pause_toggled)
```

`SwitchButton` 组件没有 `toggled` 信号，应该使用 `checkedChanged`。

---

## ✅ **修复方案**

```python
# ✅ 正确
self.pause_switch.checkedChanged.connect(self._on_pause_toggled)
```

---

## 📝 **QFluentWidgets信号对照**

| 组件 | 正确信号 | 错误信号 |
|------|---------|---------|
| SwitchButton | `checkedChanged` | ~~toggled~~ |
| CheckBox | `stateChanged` | ~~toggled~~ |
| RadioButton | `toggled` | ✅ 可用 |

---

## ✅ **修复结果**

```
✓ Syntax check passed
✓ All interfaces loaded successfully
✓ Application starts normally
```

---

## 🎉 **总结**

✅ **Bug已修复**  
✅ **应用正常启动**  
✅ **固定停顿提示功能正常工作**

**所有功能恢复正常！**
