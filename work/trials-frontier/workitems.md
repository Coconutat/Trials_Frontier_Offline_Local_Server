# Work Items

| ID | title | role | targets | surface | status | evidence | notes |
|----|-------|------|---------|---------|--------|----------|-------|
| WI-001 | Establish scope and auth | lead | case | process | completed | E-PVP-NATIVE | 复用granted/lab_only，仅本地样本和回环测试 |
| WI-PVP-001 | Reverse reward/currency contracts | cre | local APK-derived ELF | binary | completed | E-PVP-NATIVE | 见[原生笔记](<notes/pvp-reward-contract.md>)；静态分析，不是真机 |
| WI-PVP-002 | Repair settlement and persistence | lead/cae | local server | local_api | completed | E-PVP-RED,E-PVP-GREEN | 21项隔离回归通过，未部署 |
| WI-PVP-003 | Verify actual device receipt and relogin | lead | owner device | mobile | pending | | 未执行 |
| WI-PVP-004 | Outfit discount, multiple slots, remaining online businesses | cre | local server | local_api | pending | E-PVP-NATIVE | [限制和后续](<notes/2026-10-05_pvp-economy-report.md>) |

## Coverage
- [ ] Recon/analysis complete for in_scope assets
- [ ] Critical/High candidates triaged (or N/A for pure RE)
- [ ] Validated findings have Evidence (E-*)
- [ ] Path documented (attack/call/solve)
- [ ] Timeline continuous across major phases
- [ ] Report via docs-generator
- [ ] field-journal anonymized

## Refs
- skills/ops/timeline-workitem.md
- skills/ops/evidence-finding-path.md