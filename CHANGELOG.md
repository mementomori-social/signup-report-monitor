### 2.3.1: 2026-07-08

* Add CHANGELOG.md and package versioning

### 2.3.0: 2026-07-08

* Add signup IP shown under Location
* Add active IP blacklist/abuse reputation check to the AI assessment
* Change AI assessment to weigh short generic reasons for joining more skeptically
* Change AI assessment to weigh email/username identity mismatches as a real signal

### 2.2.1: 2026-07-07

* Fix Translation line showing for English/Finnish locales

### 2.2.0: 2026-07-07

* Add translation of non-English/Finnish reasons for joining

### 2.1.1: 2026-07-07

* Fix pending-account count using the v1 admin API, which ignores the status filter

### 2.1.0: 2026-07-07

* Add direct link to the signup's own application
* Add live pending-account count to the pending queue link
* Add account profile link to the approve confirmation

### 2.0.4: 2026-07-06

* Fix reaction worker not retrying whoami and initial sync on a boot-time network delay

### 2.0.3: 2026-07-06

* Change admin-action failure replies to state the reason directly in the thread
* Change README architecture diagram to Mermaid

### 2.0.2: 2026-07-06

* Fix emoji reactions sent with a variation selector not being recognised
* Change AI prompt to judge behaviour, not identity, nationality, or script

### 2.0.1: 2026-07-06

* Fix Matrix sync long-poll socket timeout causing missed reactions
* Add blank line before the AI recommendation block
* Change README title from a kebab-case slug to a human-readable heading

### 2.0.0: 2026-07-06

* Add full rewrite from PHP to a Python daemon running as a systemd service
* Add async AI bot/spam risk assessment via the claude CLI with web lookups
* Add offline GeoIP enrichment via DB-IP Lite
* Add emoji-driven approve/reject/resolve via a Matrix sync loop
* Add real Matrix mentions so the ping actually notifies
* Remove the PHP webhook handler
