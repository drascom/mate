---
id: analyze-root-files
source: user
created: "2026-05-13T01:49:59Z"
status: processing
title: Root dosyalarını analiz et
allowed_actions: ["run_bash"]
priority: normal
admin: true
retry_count: 1
started_at: "2026-05-13T01:52:03Z"
---

Kök dizindeki dosya ve klasörleri analiz et. Önce `ls -la /` ile listele, ardından tür ve boyut özeti için `du -sh /* 2>/dev/null | sort -h` çalıştır. Sistem dosyalarını değiştirme veya silme; sadece oku ve özet rapor üret.
