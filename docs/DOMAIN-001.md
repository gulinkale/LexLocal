Aşağıdaki listenin tamamı bittiğinde **DOMAIN-001 gerçekten kapanmış** olacak.

## 1. Domain analizi ve kuralları çıkarma — TAMAMLANDI

* [x] Mevcut dokümantasyon incelendi.
* [x] Schema/migration yapısı incelendi.
* [x] Mevcut kod ve testler incelendi.
* [x] Domain kavramları çıkarıldı.
* [x] State'ler çıkarıldı.
* [x] İzin verilen transition'lar çıkarıldı.
* [x] Invariant'lar çıkarıldı.
* [x] Dokümanlar arasındaki çelişkiler belirlendi.
* [x] Processing retry semantiğindeki belirsizlik tespit edildi.

---

## 2. DOMAIN-001 scope'unu kesinleştirme — TAMAMLANDI

* [x] DOMAIN-001'in sadece domain contract'larını oluşturacağı kesinleştirildi.
* [x] SQLite repository yazılmayacağı belirlendi.
* [x] Migration yazılmayacağı belirlendi.
* [x] Application use-case yazılmayacağı belirlendi.
* [x] PDF processing yapılmayacağı belirlendi.
* [x] OCR yapılmayacağı belirlendi.
* [x] Embedding/RAG algoritması yapılmayacağı belirlendi.
* [x] Foundry inference yapılmayacağı belirlendi.
* [x] PySide6 UI yapılmayacağı belirlendi.
* [x] Processing retry kuralı kesinleştirildi:

  * 1 `ProcessingJob` = 1 attempt.
  * Terminal job tekrar açılmaz.
  * Retry mevcut job'ı değiştirmez.
  * Retry yeni `ProcessingJob` oluşturur.
  * Yeni job'ın yeni ID'si ve sonraki attempt number'ı olur.
  * Yeni job oluşturma application/repository katmanının daha sonraki sorumluluğudur.

---

## 3. Domain package yapısı — TAMAMLANDI

Onaylanan yapı:

```text
src/lexlocal/domain/
├── __init__.py
├── errors.py
├── identifiers.py
├── workspace.py
├── documents.py
├── processing.py
└── retrieval.py
```

* [x] Generic `entities/`, `value_objects/`, `services/` gibi gereksiz klasörler oluşturulmadı.
* [x] Generic state-machine framework kurulmadı.
* [x] Domain event sistemi eklenmedi.
* [x] Dependency-injection sistemi eklenmedi.
* [x] `retrieval.py` domain dili için tercih edildi.

### Mevcut repository için küçük temizlik

Codex audit'inde boş bir:

```text
rag.py
```

göründü.

Onaylanan isim:

```text
retrieval.py
```

olduğu için commit öncesinde:

* [ ] Boş `rag.py` gerçekten mevcutsa kaldır.
* [ ] İhtiyaç zamanı geldiğinde `retrieval.py` kullan.
* [ ] Boş gelecek-aşama placeholder dosyalarını sırf var olsun diye commit etme.

---

# 4. Typed Identifiers — TAMAMLANDI

### 4A — Minimum domain error temeli

* [x] `DomainError`
* [x] `InvalidDomainValue`

### 4B — Typed identifier'lar

* [x] `WorkspaceId`
* [x] `DocumentId`
* [x] `DocumentVersionId`
* [x] `ProcessingJobId`
* [x] `IndexGenerationId`
* [x] `DocumentPageId`
* [x] `SourceLocatorId`
* [x] `ChunkId`
* [x] `LocalModelId`
* [x] `RetrievalRunId`
* [x] `EvidenceItemId`

Hepsi için:

* [x] UUID string validation.
* [x] Empty değer reddi.
* [x] Malformed UUID reddi.
* [x] Non-string reddi.
* [x] Canonical UUID representation.
* [x] Immutability.
* [x] Hashability.
* [x] Aynı tür + aynı UUID eşitliği.
* [x] Farklı tür + aynı UUID eşitsizliği.
* [x] UUID version zorlamaması.
* [x] UUID üretmemesi.

### 4C — Identifier testleri

* [x] 211 identifier testi geçti.
* [x] Equality testleri.
* [x] Hashing testleri.
* [x] Immutability testleri.
* [x] Canonicalization testleri.
* [x] Invalid input testleri.
* [x] Nominal type separation testleri.

**Step 4 tamamen kapandı.**

---

# 5. Typed domain failures — SIRADAKİ ADIM

Mevcut:

```text
DomainError
└── InvalidDomainValue
```

Kalan gerekli domain error türleri:

* [ ] `InvalidStateTransition`
* [ ] `WorkspaceScopeViolation`
* [ ] `RelationshipMismatch`

Hedef yapı:

```text
DomainError
├── InvalidDomainValue
├── InvalidStateTransition
├── WorkspaceScopeViolation
└── RelationshipMismatch
```

Kurallar:

* [ ] Infrastructure exception'ları domain API'sine sızmamalı.
* [ ] UI message/localization eklenmemeli.
* [ ] HTTP status code eklenmemeli.
* [ ] SQLite tipi eklenmemeli.
* [ ] Foundry tipi eklenmemeli.
* [ ] Retry metadata'sı eklenmemeli.
* [ ] Hassas belge içeriği exception içine konmamalı.
* [ ] Hata türleri yalnızca gerçekten temsil ettikleri domain ihlallerinde kullanılmalı.

---

# 6. Workspace domain contract'ı

Dosya:

```text
src/lexlocal/domain/workspace.py
```

Yapılacaklar:

* [ ] `WorkspaceState` oluştur.
* [ ] Dokümante edilmiş workspace state'lerini aynen temsil et.
* [ ] `Workspace` domain modelini oluştur.
* [ ] Workspace ID kullan.
* [ ] Workspace state invariant'larını tanımla.
* [ ] İzin verilen state transition'ları tanımla.
* [ ] Yasak transition'ları `InvalidStateTransition` ile reddet.
* [ ] Terminal state varsa tekrar açılmasını engelle.
* [ ] Workspace'in hangi işlemleri yapmaya uygun olduğunu belirleyen küçük capability/guard fonksiyonlarını oluştur.
* [ ] UI için türetilmiş state'leri burada persisted business state olarak modelleme.

Testler:

* [ ] Workspace oluşturma.
* [ ] Geçerli state transition.
* [ ] Geçersiz state transition.
* [ ] Terminal-state davranışı.
* [ ] State invariant'ları.

---

# 7. Logical Document ve Document Version contract'ları

Dosya:

```text
src/lexlocal/domain/documents.py
```

Oluşturulacak temel kavramlar:

* [ ] `LogicalDocumentState`
* [ ] `DocumentVersionState`
* [ ] `VersionNumber`
* [ ] `LogicalDocument`
* [ ] `DocumentVersion`

Logical document tarafında:

* [ ] Document'ın workspace'e ait olması.
* [ ] Document kimliği.
* [ ] ACTIVE / terminal deletion davranışının uygulanması.
* [ ] Silinmiş document üzerinde yasak işlemlerin korunması.

Document version tarafında:

* [ ] Version'ın bir logical document'a bağlı olması.
* [ ] Workspace relationship'inin tutarlı olması.
* [ ] Version number validation.
* [ ] Dokümante edilmiş version state'lerinin uygulanması.
* [ ] Dokümante edilmiş geçerli transition'ların uygulanması.
* [ ] Geçersiz transition'ların reddedilmesi.
* [ ] İlişki uyuşmazlıklarında `RelationshipMismatch` kullanılması.

Testler:

* [ ] VersionNumber geçerli/geçersiz değerleri.
* [ ] LogicalDocument equality/identity davranışları gereken ölçüde.
* [ ] Document state transition'ları.
* [ ] DocumentVersion transition'ları.
* [ ] Yanlış document/version ilişkileri.
* [ ] Workspace mismatch durumları.

---

# 8. ProcessingJob domain contract'ı

Dosya:

```text
src/lexlocal/domain/processing.py
```

Oluşturulacaklar:

* [ ] `AttemptNumber`
* [ ] `ProcessingJobState`
* [ ] `ProcessingJob`

Onaylanmış state transition'ları:

```text
QUEUED → PROCESSING
QUEUED → CANCELLED

PROCESSING → READY
PROCESSING → READY_WITH_WARNINGS
PROCESSING → FAILED
PROCESSING → CANCELLED
```

Bunların dışında:

* [ ] Geçiş reddedilmeli.
* [ ] `InvalidStateTransition` kullanılmalı.

Terminal state'ler:

```text
READY
READY_WITH_WARNINGS
FAILED
CANCELLED
```

Kurallar:

* [ ] Terminal ProcessingJob tekrar `QUEUED` olamaz.
* [ ] Terminal ProcessingJob tekrar `PROCESSING` olamaz.
* [ ] Existing job retry için değiştirilmez.
* [ ] Bir ProcessingJob tam olarak bir attempt temsil eder.
* [ ] AttemptNumber pozitif ve geçerli domain scalar olmalı.
* [ ] Job doğru DocumentVersion'a bağlı olmalı.
* [ ] Workspace relationship'leri doğrulanmalı.

Önemli:

DOMAIN-001 içinde:

* [ ] Retry için yeni job yaratma servisi yazma.
* [ ] Database'den next attempt bulma yazma.
* [ ] Transaction yazma.

Bunlar daha sonra application/repository katmanında yapılacak.

Testler:

* [ ] Bütün valid transitions.
* [ ] Bütün invalid transitions.
* [ ] Her terminal state'in immutable olması.
* [ ] AttemptNumber validation.
* [ ] DocumentVersion relationship.
* [ ] Workspace mismatch.

---

# 9. IndexGeneration domain contract'ı

Aynı dosyada:

```text
processing.py
```

bulunacak.

Oluşturulacaklar:

* [ ] `IndexGenerationState`
* [ ] `IndexGeneration`

Onaylanan temel transition modeli:

```text
STAGING → ACTIVE
STAGING → FAILED

ACTIVE → ARCHIVED
```

Yapılacaklar:

* [ ] Geçerli transition'lar.
* [ ] Geçersiz transition'lar.
* [ ] Workspace association.
* [ ] İlgili document/version/job ilişkilerinin doğrulanması.
* [ ] Aktif/archive davranışlarının domain contract olarak belirlenmesi.
* [ ] Infrastructure/index storage davranışlarının eklenmemesi.

Testler:

* [ ] Valid transition.
* [ ] Invalid transition.
* [ ] Relationship mismatch.
* [ ] Workspace mismatch.

---

# 10. Retrieval / Evidence domain contract'ları

Dosya:

```text
src/lexlocal/domain/retrieval.py
```

Scalar/value kavramları:

* [ ] `PageNumber`
* [ ] `EvidenceRank`
* [ ] `SimilarityScore`

Enums:

* [ ] `SourceLocatorKind`
* [ ] `EvidenceAvailability`
* [ ] `EvidenceSufficiency`

Evidence availability tarafında dokümante edilmiş davranış:

```text
AVAILABLE → SOURCE_DELETED
```

Evidence sufficiency:

```text
SUFFICIENT
RELATED_BUT_INSUFFICIENT
INSUFFICIENT
```

Domain modelleri:

* [ ] `SourceLocator`
* [ ] `Evidence`

Yapılacaklar:

* [ ] Source locator'ın belge/sayfa kaynak ilişkisini temsil etmesi.
* [ ] Page number validation.
* [ ] Rank validation.
* [ ] Similarity score invariant'larının dokümana göre uygulanması.
* [ ] Evidence availability transition'ı.
* [ ] Silinmiş source'un kullanılabilir evidence gibi gösterilmemesi.
* [ ] Evidence sufficiency'nin domain kavramı olarak modellenmesi.
* [ ] Retrieval eligibility guard'ın oluşturulması.
* [ ] Workspace relationship'lerinin doğrulanması.

Burada yapılmayacaklar:

* [ ] Cosine similarity algoritması yazma.
* [ ] Embedding oluşturma.
* [ ] Vector search.
* [ ] Prompt oluşturma.
* [ ] LLM çağırma.
* [ ] Foundry inference.
* [ ] RAG orchestration.

DOMAIN-001 sadece **contract** oluşturacak.

Testler:

* [ ] PageNumber.
* [ ] EvidenceRank.
* [ ] SimilarityScore.
* [ ] Availability transition.
* [ ] Evidence sufficiency değerleri.
* [ ] Source relationship.
* [ ] Workspace mismatch.
* [ ] Retrieval eligibility.

---

# 11. Workspace-scope guard'ları

Bu DOMAIN-001'in en önemli güvenlik invariant'larından biri.

Temel kural:

> Workspace A'ya ait bir domain nesnesi Workspace B'nin nesnesiyle yanlışlıkla ilişkilendirilemez.

Örneğin:

```text
Workspace A
└── Document A

Workspace B
└── ProcessingJob B
```

Şu ilişki reddedilmeli:

```text
Document A → ProcessingJob B
```

Yapılacaklar:

* [ ] Workspace ID karşılaştırma guard'ları.
* [ ] Document ↔ Version scope kontrolü.
* [ ] Version ↔ ProcessingJob scope kontrolü.
* [ ] Processing ↔ IndexGeneration scope kontrolü.
* [ ] Retrieval/Evidence ↔ source scope kontrolü.
* [ ] Cross-workspace işlemde `WorkspaceScopeViolation`.
* [ ] Aynı workspace içindeki farklı ama uyuşmayan ilişkilerde gerekiyorsa `RelationshipMismatch`.

Testler:

* [ ] Same-workspace işlemler kabul edilir.
* [ ] Cross-workspace işlemler reddedilir.
* [ ] Doğru typed exception gelir.

---

# 12. Persisted domain state ile UI state'i ayır

DOMAIN-001'in önemli mimari maddesi.

Yapılacaklar:

* [ ] Database'e yazılabilecek business state'leri domain'de açıkça tanımla.
* [ ] UI'nin göstermek için sonradan hesaplayabileceği state'leri persisted enum'a ekleme.

Örneğin UI'de:

```text
Processing...
Needs Attention
Unavailable
```

gibi bir görünüm gerekebilir.

Ama bunların her biri gerçek persisted business state değilse domain enum'a eklenmemeli.

Kontrol:

* [ ] Domain state = gerçek business fact.
* [ ] UI state = gerektiğinde persisted state'lerden türetilir.
* [ ] Domain presentation katmanına bağımlı değildir.
* [ ] PySide6 tipi domain içine girmez.

---

# 13. Domain unit test paketini tamamla

Nihai test ağacı yaklaşık:

```text
tests/unit/domain/
├── test_identifiers.py
├── test_workspace.py
├── test_documents.py
├── test_processing.py
├── test_retrieval.py
└── test_workspace_scope.py
```

Identifier:

* [x] tamamlandı.

Workspace:

* [ ] valid transitions.
* [ ] invalid transitions.
* [ ] terminal/capability behavior.

Documents:

* [ ] state transitions.
* [ ] version transitions.
* [ ] relationship invariants.
* [ ] scalar validation.

Processing:

* [ ] tüm valid transitions.
* [ ] invalid transitions.
* [ ] terminal immutability.
* [ ] one-job-one-attempt invariant.
* [ ] attempt validation.

Index:

* [ ] STAGING/ACTIVE/FAILED/ARCHIVED davranışları.

Retrieval:

* [ ] scalar validation.
* [ ] evidence availability.
* [ ] sufficiency.
* [ ] source relationships.

Workspace scope:

* [ ] cross-workspace rejection.
* [ ] same-workspace acceptance.
* [ ] doğru exception türü.

---

# 14. Architecture boundary'lerini doğrula

DOMAIN-001 bittikten sonra domain şu bağımlılıkları taşımamalı:

```text
SQLite ❌
repository ❌
PySide6 / Qt ❌
Foundry SDK ❌
application service ❌
presentation ❌
HTTP framework ❌
DI container ❌
```

İzin verilen:

```text
Python standard library ✅
domain sibling modules ✅
```

Kontroller:

* [ ] Existing architecture tests geçiyor.
* [ ] Gerekirse domain sınır testi yeni modülleri de kapsıyor.
* [ ] `domain/__init__.py` gereksiz dev re-export surface oluşturmuyor.
* [ ] Internal domain modülleri root `domain` üzerinden değil sibling module üzerinden import ediyor.

---

# 15. Bütün kalite kapılarını çalıştır

DOMAIN-001 sonunda:

```bash
uv run pytest tests/unit/domain -v
```

* [ ] PASS

```bash
uv run pytest
```

* [ ] PASS

```bash
uv run ruff check .
```

* [ ] PASS

```bash
uv run mypy src
```

* [ ] PASS

Architecture testleri:

* [ ] PASS

```bash
git diff --check
```

* [ ] PASS

---

# 16. DOMAIN-001 scope audit

Bitirmeden önce bütün diff tek tek incelenmeli.

DOMAIN-001 içinde **olmaması gereken** şeyler:

* [ ] SQLite repository implementation yok.
* [ ] Yeni migration yok.
* [ ] Unit of Work değişikliği yok.
* [ ] PDF extraction yok.
* [ ] OCR yok.
* [ ] Chunking algoritması yok.
* [ ] Embedding yok.
* [ ] NumPy retrieval yok.
* [ ] Vector DB yok.
* [ ] Foundry inference yok.
* [ ] Prompt construction yok.
* [ ] Chat orchestration yok.
* [ ] PySide6 ekranı yok.
* [ ] HTTP API yok.
* [ ] Gerçek user document handling yok.
* [ ] Gereksiz generic framework yok.
* [ ] Event bus yok.
* [ ] Dependency injection framework yok.

DOMAIN-001'in yaptığı şey:

```text
Kuralları ve kavramları tanımlar.
```

Yapmadığı şey:

```text
Bu kuralları kullanarak gerçek application workflow çalıştırmak.
```

---

# 17. Git/staged diff kontrolü

Şu anda bazı dosyalar untracked olduğu için bu özellikle önemli.

Önce:

```bash
git status --short
```

* [ ] Beklenmeyen dosya yok.

Stage edildikten sonra:

```bash
git diff --cached --stat
git diff --cached
git diff --cached --check
```

* [ ] Her satır DOMAIN-001 kapsamında.
* [ ] Boş placeholder dosyalar gereksiz yere commit edilmiyor.
* [ ] `rag.py` yanlışlıkla commit edilmiyor.
* [ ] Doğru isim `retrieval.py`.
* [ ] Cache/IDE/generated file yok.

Ardından:

* [ ] Mantıklı tek DOMAIN-001 commit veya gerektiği kadar temiz commit oluştur.
* [ ] Branch diff'i tekrar incele.
* [ ] PR oluştur.
* [ ] PR açıklamasında DOMAIN-001 contract'ları ve test sonuçlarını belirt.

---

# DOMAIN-001 final Definition of Done

Ticket ancak aşağıdakilerin **tamamı** sağlandığında kapanmalı:

* [x] Typed identifiers mevcut.
* [ ] Workspace contract mevcut.
* [ ] LogicalDocument contract mevcut.
* [ ] DocumentVersion contract mevcut.
* [ ] ProcessingJob contract mevcut.
* [ ] One-job-one-attempt kuralı kodda korunuyor.
* [ ] Terminal ProcessingJob tekrar açılamıyor.
* [ ] IndexGeneration contract mevcut.
* [ ] SourceLocator contract mevcut.
* [ ] Evidence contract mevcut.
* [ ] Evidence sufficiency contract mevcut.
* [ ] Bütün gerekli domain scalar/value object'ler doğrulanıyor.
* [ ] Bütün documented states tanımlı.
* [ ] Bütün documented valid transitions uygulanmış.
* [ ] Invalid transitions typed error üretiyor.
* [ ] Cross-workspace işlemler engelleniyor.
* [ ] Relationship mismatch'ler engelleniyor.
* [ ] Persisted state / UI state ayrımı korunuyor.
* [ ] Domain failure hierarchy tamamlanmış.
* [ ] Domain unit tests tamamlanmış.
* [ ] Full test suite geçiyor.
* [ ] Ruff geçiyor.
* [ ] mypy geçiyor.
* [ ] Architecture tests geçiyor.
* [ ] Domain SQLite bilmiyor.
* [ ] Domain Qt bilmiyor.
* [ ] Domain Foundry bilmiyor.
* [ ] Scope dışı application/infrastructure implementation eklenmemiş.
* [ ] Staged diff insan tarafından incelenmiş.
* [ ] DOMAIN-001 PR review'e hazır.

## Mevcut konum

```text
Adım 1  ✅
Adım 2  ✅
Adım 3  ✅
Adım 4  ✅ Typed Identifiers

Adım 5  ← SIRADAKİ
Adım 6
Adım 7
Adım 8
Adım 9
Adım 10
Adım 11
Adım 12
Adım 13
Adım 14
Adım 15
Adım 16
Adım 17
```

Dolayısıyla şu anda **DOMAIN-001'in temel kimlik altyapısını bitirmiş durumdayız; sıradaki iş `InvalidStateTransition`, `WorkspaceScopeViolation` ve `RelationshipMismatch` ile kalan typed domain failure sözleşmesini tamamlamak.**
