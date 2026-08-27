# SECURITY-001 — M1 sensitive-payload ve controlled-storage port'ları

Bu listenin tamamı bittiğinde **SECURITY-001 gerçekten kapanmış** olacak.

SECURITY-001 production encryption milestone'ı değildir. Amaç, M1 application
workflow'larının hassas payload'ları doğrudan plaintext SQLite alanlarına veya
kontrolsüz dosya yollarına bağlamasını önleyen replaceable sınırları kurmaktır.

```text
bootstrap composition root
    ├── application port'larını kullanır
    └── infrastructure provider'larını seçip port'lara bağlar

infrastructure provider → application port'u uygular
application → domain typed identifier'larını kullanabilir
```

Application concrete provider'ı, `sqlite3` bağlantısını, fiziksel source path'ini
ve raw encryption key'i bilmez.

---

## 1. Repository ve security-boundary analizi — TAMAMLANDI

* [x] Branch ve Git durumu kontrol edildi.
* [x] `src/lexlocal/application/`, `infrastructure/`, `bootstrap/` ve `domain/`
  tamamen incelendi.
* [x] `tests/unit/`, `tests/integration/` ve `tests/architecture/` incelendi.
* [x] `pyproject.toml` ve ilgili proje dokümanları incelendi.
* [x] İlk migration'daki `*_ciphertext` BLOB'ları, `stored_blobs` ve
  `workspace_key_records` incelendi.
* [x] SQLite ve filesystem write noktaları arandı.
* [x] Application port kalıbının `application/ports/` altında `Protocol`
  kullandığı doğrulandı.
* [x] Application service ve security port/provider paketinin henüz bulunmadığı
  doğrulandı.
* [x] Application katmanında doğrudan SQLite veya filesystem write bulunmadığı
  doğrulandı.
* [x] Mevcut write'ların infrastructure persistence ve bootstrap logging ile
  sınırlı olduğu doğrulandı.
* [x] Mevcut environment modelinin `development`, `test`, `production` olduğu
  doğrulandı; ayrı `RuntimeMode` gerekmiyor.

Repository kararı:

* Application port'ları `src/lexlocal/application/ports/` altında tutulur.
* Infrastructure concrete implementation'ları application port'larını uygular.
* Bootstrap manuel composition root'tur; DI framework kullanılmaz.
* Existing SQLite infrastructure ihlal değildir. Yasak olan, application'ın
  sensitive plaintext'i doğrudan SQLite/filesystem'e yazmasıdır.
* M1 yalnızca synthetic, anonymous ve non-sensitive fixture kullanabilir.

---

## 2. SECURITY-001 scope freeze — TAMAMLANDI

### IN SCOPE

* [x] Application-facing payload context/value contract'ları.
* [x] `SensitivePayloadCodec` ve `ControlledSourceStorage` port'ları.
* [x] Opaque `WorkspaceKeyReference` ve `ControlledSourceRef`.
* [x] Açıkça insecure, synthetic-only development provider'ları.
* [x] Mevcut `AppSettings.environment` ile explicit provider seçimi.
* [x] Production'da fail-closed rejection ve silent fallback yasağı.
* [x] Workspace/context isolation.
* [x] Application direct sensitive SQLite/filesystem write regression koruması.
* [x] Focused unit, bootstrap ve architecture testleri.

### OUT OF SCOPE

* [x] Production encryption, AES, Fernet veya crypto algorithm seçimi yok.
* [x] Key generation, derivation, wrapping, rotation veya recovery yok.
* [x] Argon2, PBKDF2, scrypt veya HKDF yok.
* [x] Keychain, Secure Enclave, master password veya Touch ID yok.
* [x] Production workspace-key lifecycle veya encrypted source storage yok.
* [x] Migration veya existing-data encryption retrofit yok.
* [x] Real user document ingestion yok.
* [x] PDF/OCR, chunking, embedding, retrieval veya RAG yok.
* [x] Foundry, prompt/chat, UI veya HTTP API yok.
* [x] Generic security framework, event bus, plugin framework, DI container veya
  service locator yok.

### Doğrulama

* [x] Bu scope uygulamaya başlamadan insan tarafından onaylandı.

### Step completion

* [x] SECURITY-001 scope'u donduruldu; yeni özellik eklenmeden Adım 3'e geçilebilir.

---

## 3. Package ve layer ownership freeze — TAMAMLANDI

### Amaç

Dosya yerleşimini implementation başlamadan kesinleştirmek.

### Dosya / dosyalar

```text
docs/SECURITY-001.md
```

Onaylanacak minimum yapı:

```text
src/lexlocal/
├── application/ports/security.py
├── infrastructure/security/
│   ├── __init__.py
│   └── insecure_development.py
└── bootstrap/
    ├── settings.py
    └── security.py

tests/
├── unit/application/ports/test_security.py
├── unit/infrastructure/security/test_insecure_development.py
├── unit/bootstrap/test_security.py
└── architecture/test_layer_boundaries.py
```

### Yapılacaklar

* [x] Application-facing values, errors ve iki port tek `security.py` içinde
  tutulacak.
* [x] Infrastructure iki ayrı development provider class'ını tek focused module'de
  tutacak.
* [x] Bootstrap provider seçimini ve composition sonucunu sahiplenecek.
* [x] Application yalnızca domain typed IDs ve kendi port'larına bağımlı olacak.
* [x] Infrastructure application port'larını uygulayabilecek.
* [x] Bootstrap application port'larını ve concrete infrastructure'ı bilecek.
* [x] Domain security/application/infrastructure'dan bağımsız kalacak.

### Yapılmayacaklar

* [x] `models.py`, `types.py`, `errors.py`, `ports.py` şeklinde single-use
  fragmentation yapılmayacak.
* [x] Yeni package convention, DI container veya domain re-export surface yok.

### Doğrulama

* [x] Önerilen her dosyanın tek ve açık layer sorumluluğu var.

### Step completion

* [x] Package/layer ownership kararı onaylandı.

---

## 4. Application security error temeli — TAMAMLANDI

### Amaç

İlk value contract'larının kullanacağı minimum typed failure temelini kurmak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
tests/unit/application/ports/test_security.py
```

### Yapılacaklar

* [x] `SecurityContractError` tanımlanmalı.
* [x] `SecurityContextMismatch(SecurityContractError)` tanımlanmalı.
* [x] Invalid application security value construction `SecurityContractError`
  ile temsil edilmeli.
* [x] Workspace/context/key/reference mismatch `SecurityContextMismatch` olmalı.
* [x] Errors payload, raw key veya physical path içermemeli.
* [x] Error inheritance ve sanitized message test edilmeli.

### Yapılmayacaklar

* [x] Bootstrap `SecurityProviderConfigurationError` henüz oluşturulmayacak.
* [x] Crypto authentication, recovery veya production integrity hierarchy yok.
* [x] Domain `WorkspaceScopeViolation` yeniden kullanılmayacak.

### Testler / doğrulama

```bash
uv run pytest tests/unit/application/ports/test_security.py -v
uv run ruff check src/lexlocal/application/ports/security.py \
  tests/unit/application/ports/test_security.py
uv run mypy src
git diff --check
```

### Step completion

* [x] Minimum application security errors implement edildi ve focused testleri geçti.

---

## 5. `WorkspaceKeyReference` — TAMAMLANDI

### Amaç

Application'ın raw workspace key yerine opaque key kimliği taşımasını sağlamak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
```

### Yapılacaklar

* [x] Frozen, slotted `WorkspaceKeyReference` oluşturulmalı.
* [x] `workspace_id: WorkspaceId` içermeli.
* [x] `key_version: int >= 1` içermeli.
* [x] Bool, zero, negatif ve non-int version reddedilmeli.
* [x] `WorkspaceId`, `lexlocal.domain.identifiers` modülünden doğrudan import edilmeli.
* [x] Immutable ve hashable olmalı.

### Yapılmayacaklar

* [x] Raw key bytes/string veya `.key`, `.key_bytes`, `.secret`, `.material` yok.
* [x] Key create/resolve/lease/destroy port'u yok.

### Doğrulama

* [x] Modül import ediliyor ve mypy geçiyor; davranış testleri Adım 6'da.

### Step completion

* [x] `WorkspaceKeyReference` minimum contract'ı tamamlandı.

---

## 6. `WorkspaceKeyReference` testleri — TAMAMLANDI

### Amaç

Key reference validation, nominal ownership ve raw-key yasağını kanıtlamak.

### Dosya / dosyalar

```text
tests/unit/application/ports/test_security.py
```

### Testler / doğrulama

* [x] Valid typed construction.
* [x] Yanlış workspace identifier tipi reddi.
* [x] Zero, negatif, bool ve non-int version reddi.
* [x] Immutability ve hashability.
* [x] Public alanlarda raw key material bulunmadığının açık testi.
* [x] `repr` içinde raw key bulunamayacağı doğrulandı.

```bash
uv run pytest tests/unit/application/ports/test_security.py -v
git diff --check
```

### Step completion

* [x] `WorkspaceKeyReference` focused testleri geçti.

---

## 7. `SensitivePayloadContext` — TAMAMLANDI

### Amaç

Payload'ı workspace, owner, field-purpose ve schema anlamına bağlamak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
```

### Yapılacaklar

Minimum contract:

```text
workspace_id: WorkspaceId
owner_id: str
purpose: str
schema_version: int >= 1
```

* [x] `workspace_id` cross-workspace substitution'ı önlemeli.
* [x] `owner_id` row/entity/snapshot kimliğini bağlamalı.
* [x] `purpose` aynı owner içindeki farklı hassas alanları ayırmalı.
* [x] `schema_version` context anlamındaki değişiklikleri açık hale getirmeli.
* [x] Owner/purpose non-empty ve non-whitespace string olmalı.
* [x] Geçerli metin sessizce trim edilmemeli.
* [x] Schema version bool olmayan pozitif int olmalı.
* [x] Immutable ve hashable olmalı.

### Yapılmayacaklar

* [x] `dict[str, Any]` metadata yok.
* [x] SQL table/column adlarını zorunlu kılan persistence coupling yok.

### Doğrulama

* [x] Modül import/mypy doğrulaması geçti; davranış testleri Adım 8'de.

### Step completion

* [x] `SensitivePayloadContext` minimum contract'ı tamamlandı.

---

## 8. `SensitivePayloadContext` testleri — TAMAMLANDI

### Amaç

Context metadata'sının exact, immutable ve workspace-aware olduğunu kanıtlamak.

### Dosya / dosyalar

```text
tests/unit/application/ports/test_security.py
```

### Testler / doğrulama

* [x] Her alan için valid/invalid construction.
* [x] Empty/whitespace owner ve purpose reddi.
* [x] Bool ve invalid schema version reddi.
* [x] Geçerli metnin trim edilmeden korunduğu.
* [x] Workspace, owner, purpose ve version değişiminin equality'yi değiştirdiği.
* [x] Immutability ve hashability.

```bash
uv run pytest tests/unit/application/ports/test_security.py -v
git diff --check
```

### Step completion

* [x] `SensitivePayloadContext` focused testleri geçti.

---

## 9. `EncodedSensitivePayload` — TAMAMLANDI

### Amaç

Raw bytes ile encoded/protected payload'ı yapısal olarak ayırmak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
```

### Yapılacaklar

```text
payload: bytes
context: SensitivePayloadContext
key_reference: WorkspaceKeyReference
format_version: int >= 1
```

* [x] Ayrı frozen, slotted nominal type olmalı.
* [x] `payload` yalnızca bytes olmalı; empty bytes geçerli olmalı.
* [x] Context ve key-reference workspace'leri eşleşmeli.
* [x] Mismatch `SecurityContextMismatch` üretmeli.
* [x] Format version bool olmayan pozitif int olmalı.
* [x] Unknown format version codec/provider tarafından reddedilecek; tahmin yok.

### Yapılmayacaklar

* [x] Public modele nonce/tag/cipher/algorithm alanları eklenmeyecek.
* [x] Encryption implementasyonu yok.

### Doğrulama

* [x] Modül import/mypy doğrulaması geçti; davranış testleri Adım 10'da.

### Step completion

* [x] `EncodedSensitivePayload` contract'ı tamamlandı.

---

## 10. `EncodedSensitivePayload` testleri — TAMAMLANDI

### Amaç

Raw/encoded ayrımını ve envelope metadata invariant'larını kanıtlamak.

### Dosya / dosyalar

```text
tests/unit/application/ports/test_security.py
```

### Testler / doğrulama

* [x] Raw bytes'tan nominal ayrım.
* [x] Valid construction ve empty payload.
* [x] Non-bytes payload reddi.
* [x] Context/key workspace mismatch reddi ve doğru exception.
* [x] Invalid/bool format version reddi.
* [x] Immutability ve metadata preservation.

```bash
uv run pytest tests/unit/application/ports/test_security.py -v
git diff --check
```

### Step completion

* [x] `EncodedSensitivePayload` focused testleri geçti.

---

## 11. `ControlledSourceRef` — TAMAMLANDI

### Amaç

Application'a physical path yerine workspace-owned opaque source token vermek.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
```

### Yapılacaklar

* [x] Frozen, slotted `ControlledSourceRef` oluşturulmalı.
* [x] `workspace_id: WorkspaceId` içermeli.
* [x] `value: str` non-empty, non-whitespace opaque token olmalı.
* [x] Geçerli token sessizce trim edilmemeli.
* [x] Immutable ve hashable olmalı.
* [x] Aynı token farklı workspace'te aynı reference sayılmamalı.

### Yapılmayacaklar

* [x] `Path`, relative/absolute path veya provider location alanı yok.
* [x] Path parsing/traversal application sorumluluğu değil.
* [x] Reference generation application API'sine verilmez.

### Doğrulama

* [x] Modül import/mypy doğrulaması geçti; davranış testleri Adım 12'de.

### Step completion

* [x] `ControlledSourceRef` contract'ı tamamlandı.

---

## 12. `ControlledSourceRef` testleri — TAMAMLANDI

### Amaç

Opaque reference, ownership ve path-leakage kurallarını kanıtlamak.

### Dosya / dosyalar

```text
tests/unit/application/ports/test_security.py
```

### Testler / doğrulama

* [x] Valid/invalid construction.
* [x] Empty/whitespace/non-string token reddi.
* [x] Immutability ve hashability.
* [x] Cross-workspace nominal ayrım.
* [x] Public API'de `Path` veya physical-location alanı olmadığı.

```bash
uv run pytest tests/unit/application/ports/test_security.py -v
git diff --check
```

### Step completion

* [x] `ControlledSourceRef` focused testleri geçti.

---

## 13. `SensitivePayloadCodec` application port'u — TAMAMLANDI

### Amaç

Sensitive payload transform davranışını crypto implementasyonundan ayırmak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
```

### Yapılacaklar

```python
class SensitivePayloadCodec(Protocol):
    def encode(
        self,
        plaintext: bytes,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> EncodedSensitivePayload: ...

    def decode(
        self,
        encoded: EncodedSensitivePayload,
        *,
        context: SensitivePayloadContext,
        key_reference: WorkspaceKeyReference,
    ) -> bytes: ...
```

* [x] Encode/decode exact context ve key reference almalı.
* [x] Port bytes-in/typed-envelope-out ve tersini tanımlamalı.
* [x] Concrete provider substitution mümkün olmalı.

### Yapılmayacaklar

* [x] Algorithm, nonce, KDF, key resolver, persistence veya SQLite bilgisi yok.
* [x] Provider selection veya concrete development import'u yok.

### Testler / doğrulama

* [x] Strict mypy, Protocol signature'ını test double ile doğrulamalı.
* [x] Application modülü infrastructure import etmemeli.

### Step completion

* [x] `SensitivePayloadCodec` port'u tanımlandı ve type-check edildi.

---

## 14. `ControlledSourceStorage` application port'u — TAMAMLANDI

### Amaç

M1 source store/read/cleanup davranışını physical storage'dan ayırmak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
```

### Yapılacaklar

```python
class ControlledSourceStorage(Protocol):
    def store(self, workspace_id: WorkspaceId, source: bytes) -> ControlledSourceRef: ...
    def read(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> bytes: ...
    def delete(self, workspace_id: WorkspaceId, reference: ControlledSourceRef) -> None: ...
```

* [x] `store`, `read`, `delete` dışında operation eklenmemeli.
* [x] Read/delete her çağrıda workspace ownership doğrulayabilmeli.
* [x] Delete failed/cancelled staging ve test temizliği içindir.
* [x] Port physical path döndürmemeli.

### Yapılmayacaklar

* [x] Listing, rename, glob, full CRUD, atomic encryption, streaming veya temp-file
  API'si yok.
* [x] Application filesystem write API'si yok.

### Testler / doğrulama

* [x] Strict mypy, Protocol signature'ını test double ile doğrulamalı.

### Step completion

* [x] `ControlledSourceStorage` port'u tanımlandı ve type-check edildi.

---

## 15. Application-port contract audit — TAMAMLANDI

### Amaç

Tüm application-facing vocabulary'nin birlikte minimal ve tutarlı olduğunu
doğrulamak.

### Dosya / dosyalar

```text
src/lexlocal/application/ports/security.py
tests/unit/application/ports/test_security.py
```

### Doğrulama

* [x] Bütün values frozen/slotted, invalid construction immediate failure.
* [x] `dict[str, Any]`, raw key ve physical path yok.
* [x] Raw/encoded nominal ayrım var.
* [x] İki Protocol concrete infrastructure import'u gerektirmiyor.
* [x] Her public abstraction'ın açık M1 gerekçesi var.
* [x] Duplicate veya future-only abstraction yok.

```bash
uv run pytest tests/unit/application/ports/test_security.py -v
uv run ruff check src/lexlocal/application/ports/security.py \
  tests/unit/application/ports/test_security.py
uv run mypy src
git diff --check
```

### Step completion

* [x] Application security port paketi eksiksiz ve focused gates temiz.

---

## 16. Development-only payload codec — TAMAMLANDI

### Amaç

Synthetic M1 fixture'ları için encryption iddiası taşımayan replaceable codec sağlamak.

### Dosya / dosyalar

```text
src/lexlocal/infrastructure/security/__init__.py
src/lexlocal/infrastructure/security/insecure_development.py
```

### Yapılacaklar

* [x] `InsecureDevelopmentOnlyPayloadCodec` ayrı class olarak oluşturulmalı.
* [x] Plaintext bytes'ı typed envelope içinde taşımalı.
* [x] Format version açık ve doğrulanabilir olmalı.
* [x] Encode context/key workspace mismatch'ini reddetmeli.
* [x] Decode caller context/key'i encoded metadata ile exact karşılaştırmalı.
* [x] Mismatch `SecurityContextMismatch` üretmeli.
* [x] Unknown format version reddedilmeli; tahmin edilmemeli.
* [x] Empty bytes round-trip desteklenmeli.

### Yapılmayacaklar

* [x] Encryption, obfuscation veya production-safety iddiası yok.
* [x] Raw key isteme/saklama yok.
* [x] Storage sorumluluğu bu class'a eklenmez.

### Doğrulama

* [x] Modül import ve strict mypy geçiyor; focused davranış testleri Adım 17'de.

### Step completion

* [x] Development-only codec implement edildi.

---

## 17. Development-only payload codec testleri — TAMAMLANDI

### Dosya / dosyalar

```text
tests/unit/infrastructure/security/test_insecure_development.py
```

### Testler / doğrulama

* [x] Synthetic bytes ve empty bytes round-trip.
* [x] Context/key metadata preservation.
* [x] Wrong workspace, owner, purpose, schema veya key reference reddi.
* [x] Encode workspace mismatch reddi.
* [x] Unknown format version reddi.
* [x] Doğru typed exception ve immutable result.
* [x] Provider filesystem'e yazmıyor.

```bash
uv run pytest tests/unit/infrastructure/security/test_insecure_development.py -v
git diff --check
```

### Step completion

* [x] Development codec focused testleri geçti.

---

## 18. Development-only controlled storage — TAMAMLANDI

### Amaç

Synthetic M1 source lifecycle'ını plaintext filesystem oluşturmadan sağlamak.

### Dosya / dosyalar

```text
src/lexlocal/infrastructure/security/insecure_development.py
```

### Yapılacaklar

* [x] `InsecureDevelopmentOnlyControlledSourceStorage` ayrı class olmalı.
* [x] Storage in-memory olmalı.
* [x] `store` opaque `ControlledSourceRef` üretmeli.
* [x] `read/delete`, caller workspace ile reference workspace'ini eşleştirmeli.
* [x] Cross-workspace kullanım `SecurityContextMismatch` üretmeli.
* [x] Unknown/deleted reference sanitized `SecurityContractError` üretmeli.
* [x] Delete sonrası payload erişilememeli.

### Yapılmayacaklar

* [x] Filesystem write veya persistent storage garantisi yok.
* [x] Physical path, listing, rename veya payload codec sorumluluğu yok.

### Doğrulama

* [x] Modül import/mypy doğrulaması geçti; focused testler Adım 19'da.

### Step completion

* [x] Development-only controlled storage implement edildi.

---

## 19. Development controlled-storage testleri — TAMAMLANDI

### Dosya / dosyalar

```text
tests/unit/infrastructure/security/test_insecure_development.py
```

### Testler / doğrulama

* [x] Store/read/delete lifecycle.
* [x] Empty ve synthetic bytes davranışı.
* [x] Opaque, workspace-owned reference üretimi.
* [x] Cross-workspace read/delete reddi.
* [x] Deleted/unknown reference sanitized failure.
* [x] Workspace A kaydı Workspace B'den okunamıyor.
* [x] Fiziksel path leakage ve filesystem write yok.

```bash
uv run pytest tests/unit/infrastructure/security/test_insecure_development.py -v
git diff --check
```

### Step completion

* [x] Development storage focused testleri geçti.

---

## 20. Synthetic-fixture safety boundary — TAMAMLANDI

### Amaç

Development provider'ların yanlışlıkla gerçek-user/release desteği sayılmasını önlemek.

### Dosya / dosyalar

```text
src/lexlocal/infrastructure/security/insecure_development.py
tests/unit/infrastructure/security/test_insecure_development.py
```

### Yapılacaklar

* [x] Module ve class docstring'lerinde şu etiketler bulunmalı:

```text
DEVELOPMENT ONLY
SYNTHETIC FIXTURES ONLY
NOT RELEASE SAFE
NOT FOR REAL USER DOCUMENTS
```

* [x] Test fixtures yalnızca synthetic/anonymous bytes kullanmalı.
* [x] Provider persistence veya at-rest confidentiality garantisi vermemeli.
* [x] General/release-safe görünen isimle export edilmemeli.
* [x] Real legal document, secret, raw key veya `.env` eklenmemeli.

### Doğrulama

* [x] Risk-label testleri ve source audit geçti.

### Step completion

* [x] Synthetic-only sınır görünür ve test edilebilir durumda.

---

## 21. Security-provider setting — TAMAMLANDI

### Amaç

Provider seçimini mevcut configuration modeline explicit biçimde eklemek.

### Dosya / dosyalar

```text
src/lexlocal/bootstrap/settings.py
tests/unit/bootstrap/test_settings.py
```

### Yapılacaklar

* [x] `AppSettings.security_provider: str` eklenmeli.
* [x] `LEXLOCAL_SECURITY_PROVIDER` okunmalı.
* [x] Canonical provider adı `insecure-development-only` olmalı.
* [x] Development/test default'u insecure provider olabilir.
* [x] Production için insecure default/fallback oluşturulmamalı.
* [x] Existing `environment` modeli aynen kullanılmalı.
* [x] Default, explicit ve invalid/missing seçim test edilmeli.

### Yapılmayacaklar

* [x] Yeni `RuntimeMode`, config framework veya secret config yok.
* [x] Concrete provider burada instantiate edilmez.

### Testler / doğrulama

```bash
uv run pytest tests/unit/bootstrap/test_settings.py -v
uv run mypy src
git diff --check
```

### Step completion

* [x] Security-provider setting ve focused testleri tamamlandı.

---

## 22. Bootstrap security composition contract'ı — TAMAMLANDI

### Amaç

İki application port'unu bootstrap'ta tek açık composition sonucu olarak bağlamak.

### Dosya / dosyalar

```text
src/lexlocal/bootstrap/security.py
tests/unit/bootstrap/test_security.py
```

### Yapılacaklar

* [x] Küçük immutable `SecurityProviders` composition result'u oluşturulmalı.
* [x] Result, `SensitivePayloadCodec` ve `ControlledSourceStorage` typed alanlarını
  taşımalı.
* [x] Provider factory/selection bootstrap'ta olmalı.
* [x] Concrete development provider yalnızca bootstrap ve infrastructure'da bilinmeli.
* [x] Bootstrap configuration error ihtiyacı doğduğu bu adımda minimum
  `SecurityProviderConfigurationError` oluşturulmalı.
* [x] Error sanitized olmalı.

### Yapılmayacaklar

* [x] Application provider seçmez.
* [x] DI container/service locator yok.
* [x] Startup application service veya workflow eklenmez.

### Doğrulama

* [x] Factory sonucu iki Protocol ile mypy uyumlu.

### Step completion

* [x] Bootstrap composition contract'ı hazır.

---

## 23. Environment/provider selection kuralları — TAMAMLANDI

### Amaç

Development ve test composition'larının explicit provider seçimini tanımlamak.

### Dosya / dosyalar

```text
src/lexlocal/bootstrap/security.py
tests/unit/bootstrap/test_security.py
```

### Yapılacaklar

* [x] `development + insecure-development-only` kabul edilmeli.
* [x] `test + insecure-development-only` kabul edilmeli.
* [x] Unknown provider her environment'ta hard failure olmalı.
* [x] Selection sonucu iki ayrı provider class'ını içermeli.
* [x] No implicit registry/plugin discovery.

### Yapılmayacaklar

* [x] Production acceptance bu adımda eklenmez; Adım 24 fail-closed davranışı
  tamamlar.
* [x] Fake secure provider yok.

### Doğrulama

* [x] Development/test/unknown focused selection testleri geçiyor.

### Step completion

* [x] Non-release provider selection kuralları tamamlandı.

---

## 24. Production fail-closed rejection — TAMAMLANDI

### Amaç

Release composition'ın insecure provider'a sessizce düşmesini imkânsız kılmak.

### Dosya / dosyalar

```text
src/lexlocal/bootstrap/security.py
tests/unit/bootstrap/test_security.py
```

### Yapılacaklar

Bu repository'de release karşılığı `environment == "production"` kabul edilir.

* [x] `production + insecure-development-only` hard failure.
* [x] Production missing provider için insecure fallback yok.
* [x] Release-safe provider'ın SECURITY-001'de henüz bulunmadığı açıkça kabul edilir.
* [x] Güvenli provider gelene kadar production composition fail closed eder.
* [x] Failure provider kullanılmadan ve sensitive workflow başlamadan oluşur.
* [x] Error payload, key veya source content içermez.

Beklenen matris:

| Environment | Provider | Sonuç |
|---|---|---|
| `development` | `insecure-development-only` | kabul |
| `test` | `insecure-development-only` | kabul |
| `production` | `insecure-development-only` | hard failure |
| herhangi | unknown | hard failure |
| `production` | missing/release-safe provider yok | hard failure; fallback yok |

### Step completion

* [x] Production fail-closed kuralı implement edildi.

---

## 25. Provider-selection matrix testleri — TAMAMLANDI

### Amaç

Settings, selection, composition ve release rejection davranışını birlikte kanıtlamak.

### Dosya / dosyalar

```text
tests/unit/bootstrap/test_settings.py
tests/unit/bootstrap/test_security.py
```

### Testler / doğrulama

* [x] Matrisin her satırı test edildi.
* [x] No silent insecure fallback açıkça test edildi.
* [x] Unknown/unsupported provider test edildi.
* [x] Composition iki application port'unu sağlıyor.
* [x] Application concrete provider import etmiyor.
* [x] Configuration error sanitized.

```bash
uv run pytest tests/unit/bootstrap/test_settings.py \
  tests/unit/bootstrap/test_security.py -v
git diff --check
```

### Step completion

* [x] Provider selection ve release rejection test paketi geçti.

---

## 26. Workspace/context isolation audit — TAMAMLANDI

* [x] `WorkspaceKeyReference` `WorkspaceId` ownership taşıyor.
* [x] Context/key workspace mismatch construction/encode aşamasında reddediliyor.
* [x] Encoded payload context/key workspace'leri eşleşiyor.
* [x] Decode supplied context/key encoded metadata ile exact eşleşiyor.
* [x] Controlled source read/delete caller workspace'i reference ile eşleştiriyor.
* [x] Workspace A payload/source/key'i Workspace B için kullanılamıyor.
* [x] Workspace mismatch identity/format değerlendirmesinden önce reddediliyor.
* [x] Doğru application-facing typed error kullanılıyor.

### Step completion

* [x] Bütün workspace/context isolation yolları implementasyon ve testlerle tutarlı.

---

## 27. Application plaintext-write regression guards — TAMAMLANDI

### Amaç

Application service'lerinin port'ları bypass etmesini mimari olarak engellemek.

### Dosya / dosyalar

```text
tests/architecture/test_layer_boundaries.py
```

### Yapılacaklar

* [x] Application `sqlite3` import'u reddedilmeli.
* [x] Application raw SQL (`INSERT`, `UPDATE`, `CREATE TABLE` vb.) reddedilmeli.
* [x] Write-mode `open`, `Path.write_bytes`, `Path.write_text`, `shutil.copy` ve
  `copyfile` direct controlled-source bypass'ları reddedilmeli.
* [x] AST tabanlı denetim kullanılmalı; brittle substring testi olmamalı.
* [x] Mevcut AST helpers genişletilmeli.

### Yapılmayacaklar

* [x] `pathlib` veya filesystem API'leri global olarak yasaklanmayacak.
* [x] Infrastructure SQLite/filesystem kullanımı genel ihlal sayılmayacak.
* [x] Existing bootstrap log-directory creation ihlal sayılmayacak.
* [x] İkinci architecture framework/walker kurulmayacak.

### Doğrulama

* [x] Guard'ların ilgili kötü örnekleri yakaladığı focused regression testiyle
  veya mevcut AST fixture tekniğiyle kanıtlandı.

### Step completion

* [x] Application direct-write regression guards eklendi.

---

## 28. Architecture boundary validation — TAMAMLANDI

* [x] Application → infrastructure security import'u mevcut layer rule ile reddediliyor.
* [x] Domain application/security/infrastructure'dan bağımsız.
* [x] Bootstrap concrete provider bilebilir.
* [x] Infrastructure application port'unu uygulayabilir.
* [x] Presentation concrete infrastructure security provider'ını import edemez.
* [x] Application `sqlite3`, raw SQL ve direct controlled-source writes kullanamaz.
* [x] Approved infrastructure/bootstrap kullanımları false positive üretmez.

```bash
uv run pytest tests/architecture -v
git diff --check
```

### Step completion

* [x] SECURITY-001 architecture boundaries eksiksiz ve testleri geçiyor.

---

## 29. Raw-key ve plaintext audit — TAMAMLANDI

```bash
rg -n "key_bytes|raw_key|secret_key|encryption_key|plaintext" src tests
rg -n "sqlite3|INSERT|UPDATE|executemany" src/lexlocal/application
rg -n "write_bytes|write_text|copyfile|shutil.copy|open\(" src/lexlocal/application
rg -n "InsecureDevelopmentOnly" src tests
```

* [x] Raw key public field/signature içinde yok.
* [x] Application sensitive plaintext'i SQLite'a yazmıyor.
* [x] Application controlled source'u doğrudan dosyaya yazmıyor.
* [x] Insecure provider yalnızca infrastructure, bootstrap ve testlerde referanslı.
* [x] Error/log mesajlarında fixture payload yok.
* [x] Existing infrastructure SQLite kullanımı yanlışlıkla ihlal sayılmadı.

### Step completion

* [x] Raw-key/plaintext audit temiz.

---

## 30. Development-provider warning audit — TAMAMLANDI

* [x] Module/class docstring'leri dört zorunlu risk etiketini içeriyor.
* [x] Settings/help text gerçek document kullanımını teşvik etmiyor.
* [x] Production error henüz var olmayan provider'ı uydurmuyor.
* [x] Provider encryption veya confidentiality iddiasında bulunmuyor.
* [x] M1 test-data sınırı docs/tests içinde görünür.
* [x] External demo, release candidate ve packaged app insecure provider'ı kabul etmiyor.

### Step completion

* [x] Development-provider risk documentation eksiksiz.

---

## 31. Dependency-direction audit — TAMAMLANDI

| Contract | M1 gerekçesi |
|---|---|
| `WorkspaceKeyReference` | Raw key'i application'dan uzak tutmak |
| `SensitivePayloadContext` | Workspace/owner/purpose/version binding'i retrofit etmemek |
| `EncodedSensitivePayload` | Raw ile persistence-safe payload'ı ayırmak |
| `SensitivePayloadCodec` | Sensitive payload transform'unu provider arkasına almak |
| `ControlledSourceRef` | Physical path bağımlılığını engellemek |
| `ControlledSourceStorage` | Source store/read/cleanup akışını replaceable yapmak |

* [x] Application yalnızca domain typed IDs ve application port'larına bağımlı.
* [x] Infrastructure application port'larını uyguluyor; ters dependency yok.
* [x] Bootstrap provider seçiyor; application seçim yapmıyor.
* [x] Domain security infrastructure bilmiyor.
* [x] Her public abstraction'ın gerçek M1 gerekçesi var.

### Step completion

* [x] Dependency direction ve contract necessity audit'i temiz.

---

## 32. Overengineering audit — TAMAMLANDI

* [x] Generic crypto/security/value-object framework yok.
* [x] Provider registry/plugin architecture yok.
* [x] DI container/service locator/event bus yok.
* [x] Generic repository/entity hierarchy yok.
* [x] Key manager/session/recovery service yok.
* [x] Algorithm registry/envelope parser yok.
* [x] Fake production encryption yok.
* [x] Streaming/random-access abstraction erken eklenmedi.
* [x] Full blob CRUD/listing/path API'si yok.
* [x] İkinci runtime-mode abstraction yok.
* [x] Gereksiz domain değişikliği yok.

### Step completion

* [x] SECURITY-001 minimal ve focused kaldı.

---

## 33. Quality gates — TAMAMLANDI

```bash
uv run pytest \
  tests/unit/application/ports/test_security.py \
  tests/unit/infrastructure/security/test_insecure_development.py \
  tests/unit/bootstrap/test_security.py -v
```

* [x] PASS — 149 passed

```bash
uv run pytest tests/architecture -v
```

* [x] PASS — 19 passed

```bash
uv run pytest
```

* [x] PASS — 942 passed, 1 skipped

```bash
uv run ruff check .
```

* [x] PASS

```bash
uv run mypy src
```

* [x] PASS — 32 source files

```bash
git diff --check
```

* [x] PASS

Future test count hardcode edilmez; final audit gerçek sonucu yazar.

### Step completion

* [x] Bütün quality gates geçti.

---

## 34. Strict SECURITY-001 scope audit — TAMAMLANDI

Diff içinde aşağıdakilerin bulunmadığı doğrulanmalı:

* [x] Production crypto/AES/Fernet veya crypto dependency yok.
* [x] KDF/HKDF/password/recovery implementasyonu yok.
* [x] Key generation/wrapping/rotation/lifecycle yok.
* [x] Keychain/Secure Enclave/Touch ID yok.
* [x] Production encrypted source provider yok.
* [x] Migration/schema değişikliği yok.
* [x] Repository/application workflow implementasyonu yok.
* [x] Real document/PDF/OCR yok.
* [x] Chunking/embedding/vector search/RAG yok.
* [x] Foundry/prompt/chat/UI/HTTP yok.
* [x] Generic framework/event bus/DI/plugin yok.
* [x] Real user document, secret, raw key veya `.env` yok.

### Step completion

* [x] Strict scope audit temiz.

---

## 35. Encryption-retrofit-risk audit — TAMAMLANDI

Bu ticket'ın özel final acceptance kriteri:

* [x] Application raw encryption key kabul etmiyor/döndürmüyor.
* [x] Raw ve encoded payload yapısal olarak ayrı.
* [x] Payload context workspace, owner, purpose ve schema version içeriyor.
* [x] Application `sqlite3` veya sensitive SQL representation bilmiyor.
* [x] Application physical controlled-source path'ine bağımlı değil.
* [x] Application controlled source için port'a bağımlı.
* [x] Application concrete development provider'ı bilmiyor.
* [x] Real provider daha sonra aynı port'ların arkasına eklenebilir.
* [x] Provider selection bootstrap'ta.
* [x] Production insecure provider'a sessizce düşmüyor.
* [x] Workspace/context binding şimdiden mevcut.
* [x] Production encryption eklemek application workflow signature'larını yeniden
  tasarlamayı gerektirmiyor.

### Step completion

* [x] M1 encryption-retrofit dependency oluşturmuyor.

---

## 36. Git, staged diff, commit ve PR

Önerilen branch:

```text
feature/security-001-storage-ports
```

Önerilen commit:

```text
feat(security): define M1 sensitive storage ports
```

Önerilen PR title:

```text
SECURITY-001 — Define M1 sensitive-payload and controlled-storage ports
```

```bash
git status --short
```

* [ ] Beklenmeyen/unrelated dosya yok.
* [ ] Secret, raw key, `.env` veya real user document yok.
* [ ] Generated/cache/IDE file yok.
* [ ] Out-of-scope crypto yok.

Stage edildikten sonra:

```bash
git diff --cached --stat
git diff --cached
git diff --cached --check
```

* [ ] Her staged dosya ve satır SECURITY-001 kapsamında.
* [ ] Staged whitespace kontrolü geçti.
* [ ] Staged diff insan tarafından incelendi.
* [ ] Commit oluşturuldu.
* [ ] PR açıklaması contract'ları, synthetic boundary'yi, release rejection'ı ve
  gerçek test sonuçlarını içeriyor.

### Step completion

* [ ] SECURITY-001 commit/PR review'e hazır.

---

# SECURITY-001 final Definition of Done

* [x] Application-facing payload codec port mevcut.
* [x] Controlled source-storage port mevcut.
* [x] Workspace key-reference contract mevcut.
* [x] Raw encryption key application boundary'yi geçmiyor.
* [x] Contextual payload metadata contract mevcut ve doğrulanıyor.
* [x] Encoded payload raw payload'dan yapısal olarak ayrı.
* [x] Controlled source reference opaque ve physical path taşımıyor.
* [x] Workspace ownership/isolation gerekli bütün işlemlerde korunuyor.
* [x] Application concrete security/storage provider'a bağımlı değil.
* [x] İki ayrı development-only insecure provider mevcut.
* [x] Provider'lar development/synthetic-only olarak açıkça işaretli.
* [x] Development storage in-memory ve filesystem'e plaintext yazmıyor.
* [x] Release composition insecure provider'ı reddediyor.
* [x] Silent insecure fallback yok.
* [x] Unknown/unsupported provider davranışı tanımlı.
* [x] Direct sensitive SQLite write application service'lerinde yok.
* [x] Direct controlled-source plaintext write application service'lerinde yok.
* [x] Provider selection test edildi.
* [x] Contextual metadata test edildi.
* [x] Release rejection test edildi.
* [x] Workspace/context substitution test edildi.
* [x] Architecture boundaries test edildi.
* [x] Domain security infrastructure'dan bağımsız kaldı.
* [x] Production encryption uygulanmadı.
* [x] Keychain/Secure Enclave/master password/Touch ID uygulanmadı.
* [x] Real user-document desteği eklenmedi.
* [x] Generic security framework eklenmedi.
* [x] Security-specific tests geçti.
* [x] Full pytest geçti.
* [x] Ruff geçti.
* [x] mypy geçti.
* [x] Architecture tests geçti.
* [x] `git diff --check` geçti.
* [x] Strict scope audit tamamlandı.
* [x] Retrofit-risk audit tamamlandı.
* [ ] Staged diff incelendi.
* [ ] PR review'e hazır.

## Mevcut konum

```text
Adım 1  ✅ Repository ve security-boundary analizi
Adım 2  ✅ SECURITY-001 scope freeze
Adım 3  ✅ Package ve layer ownership freeze
Adım 4  ✅ Application security error temeli
Adım 5  ✅ WorkspaceKeyReference
Adım 6  ✅ WorkspaceKeyReference testleri
Adım 7  ✅ SensitivePayloadContext
Adım 8  ✅ SensitivePayloadContext testleri
Adım 9  ✅ EncodedSensitivePayload
Adım 10 ✅ EncodedSensitivePayload testleri
Adım 11 ✅ ControlledSourceRef
Adım 12 ✅ ControlledSourceRef testleri
Adım 13 ✅ SensitivePayloadCodec application port'u
Adım 14 ✅ ControlledSourceStorage application port'u
Adım 15 ✅ Application-port contract audit
Adım 16 ✅ Development-only payload codec
Adım 17 ✅ Development-only payload codec testleri
Adım 18 ✅ Development-only controlled storage
Adım 19 ✅ Development controlled-storage testleri
Adım 20 ✅ Synthetic-fixture safety boundary
Adım 21 ✅ Security-provider setting
Adım 22 ✅ Bootstrap security composition contract'ı
Adım 23 ✅ Environment/provider selection kuralları
Adım 24 ✅ Production fail-closed rejection
Adım 25 ✅ Provider-selection matrix testleri
Adım 26 ✅ Workspace/context isolation audit
Adım 27 ✅ Application plaintext-write regression guards
Adım 28 ✅ Architecture boundary validation
Adım 29 ✅ Raw-key ve plaintext audit
Adım 30 ✅ Development-provider warning audit
Adım 31 ✅ Dependency-direction audit
Adım 32 ✅ Overengineering audit
Adım 33 ✅ Quality gates
Adım 34 ✅ Strict SECURITY-001 scope audit
Adım 35 ✅ Encryption-retrofit-risk audit
Adım 36 ← MEVCUT: Git, staged diff, commit ve PR
```

Mevcut görev: **Adım 36 — Git, staged diff, commit ve PR.**
