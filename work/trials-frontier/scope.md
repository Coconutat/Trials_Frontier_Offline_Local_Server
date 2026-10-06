# Case Scope

## meta
- case_id: trials-frontier
- created: 2026-10-03T13:08:41.5275608+08:00
- operator: local
- project_root: <repo>
- primary_skill: apk-reverse/SKILL.md
- primary_id: R1
- lead_role: lead
- specialist_roles: [cre, cae, doc]
- hint: Trials Frontier com.ubisoft.redlynx.trialsfrontier.ggp 停服复活：去广告、解锁内容、最小本地服务器
- preset: own-system

## auth
- status: granted
- basis: own_system
- evidence_of_auth: preset:own-system/lab
- MUST NOT proceed if status != granted

## in_scope
- assets:
  - <repo>\APKS\特技摩托前线\7.9.4 带剧情不减反增车不全.apk
- surfaces: [mobile, binary, local_api]
- activities: [offline_reverse, local_server_repair, isolated_regression]
- continuation: 2026-10-05 用户要求继续路线图第3条；只读取既有样本及派生产物、修改本项目服务器和文档；HTTP测试限临时127.0.0.1端口，不连接官方服务/设备，不修改真实玩家状态。

## out_of_scope
- assets: []
- activities: [dos, phishing_real_users, unrestricted_exfil]

## network_profile
- mode: lab_only
- notes: |
    offline | lab_only | authorized_target_only | unrestricted_lab
    Change mode only after auth.status = granted.

## deliverables
- report: true
- field_journal: true
- diagrams: true
- timeline: true

## constraints
- timebox: {}
- stealth: low
- data_handling: anonymize

## signoff
- ready_for_act: true
- checklist:
  - [x] auth.status = granted
  - [x] in_scope.assets non-empty OR offline sample path set
  - [x] network_profile.mode chosen
  - [ ] out_of_scope reviewed
  - [ ] roles assigned (see skills/ops/role-map.md)

## ops_refs
- skills/ops/scope-contract.md
- skills/ops/evidence-finding-path.md
- skills/ops/role-map.md
- skills/ops/timeline-workitem.md
- skills/ops/IDENTITY.md