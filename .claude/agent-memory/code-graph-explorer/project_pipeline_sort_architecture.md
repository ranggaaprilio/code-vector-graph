---
name: project-pipeline-sort-architecture
description: How sort/filter is implemented in the onebid project-pipeline module — key files, patterns, and the modifiedDate/modifiedAt field disambiguation
metadata:
  type: project
---

The project-pipeline sort/filter stack lives entirely in the backend_nodejs_global_tnlm service.

Key files:
- `src/project-pipeline/dsl/detail-query-builder.ts` — central DSL class (DetailQueryBuilder). All sort logic lives here.
- `src/project-pipeline/usecases/find-project.usecase.ts` — maps FindProjectQueryDto + FindProjectBodyDto → DetailFilterParams → DetailQueryBuilder
- `src/project-pipeline/dto/find-project-query.dto.ts` — extends QueryStringDto (inherits sortBy/orderBy)
- `src/utils/dto/query-string.dto.ts` — base DTO with sortBy/orderBy as plain optional strings (no enum validation)
- `src/project-pipeline/repositories/detail-elastic.repository.ts` — executes ES queries

Sort pattern in DetailQueryBuilder:
1. `getSortableFields()` returns a map of sortBy key → ES field name (for simple field sorts)
2. Dedicated private methods handle special cases: `sortByModifiedAt()`, `sortByCreatedAt()`, `sortByLastUpdated()`, `sortByStatus()`, `sortByFieldsUsingScript()`
3. `sortByFields()` handles the lookup-map based sorts (used in `build()`)
4. `sortByFieldsUsingScript()` handles the same + script sorts (used in `buildWithFilter()`)
5. `DATE_SORT_FIELDS` static Set determines unmapped_type for `pushFieldSort()`

Existing sortBy key values (case-sensitive, as passed in the filter):
- projectName, projectType, projectValue, projectStage, projectId, ownerhsipType, developmentType, finalBidDate, estimatedValueLow, estimatedValueHigh (via getSortableFields map)
- modifiedAt (dedicated sortByModifiedAt method — uses a Painless script over modifiedDate || createdAt)
- createdAt (dedicated sortByCreatedAt method)
- lastUpdated (isLite=1 only — maps to projectPublishedDate)
- early_status / latest_status (isLite=1 only — maps to ProjectStatusRanking)

The "last update date" concept maps to TWO ES fields:
- `modifiedDate` (type: date) — raw project modification date stored in ES index
- `modifiedAt` (type: date) — a pipeline-level field used as tiebreaker in name sorts
- `lastUpdateDate` — field on ProjectElasticEntity / ProjectInterface / ProjectResponseDto (display field)
The `sortByModifiedAt()` method already handles `sortBy === 'modifiedAt'` with a Painless script that falls back to createdAt if modifiedDate is empty.

**Why:** modifiedAt sort is already implemented for the project-pipeline. `lastUpdateDate` on the ES entity appears to be a display/response field, not used as the primary sort target.

**How to apply:** When asked to add "sort by last update date" to the project search (not project-pipeline), use `modifiedDate` as the ES field (it is in DATE_SORT_FIELDS). Add it to `getSortableFields()` or add a dedicated `sortByModifiedDate()` method following the `sortByCreatedAt()` pattern.
