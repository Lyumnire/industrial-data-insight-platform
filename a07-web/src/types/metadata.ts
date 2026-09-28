// AI-assisted
/**
 * S3 元数据资源中心类型 —— docs/api/README.md §2（主控冻结契约）+ a07-server MetadataDtos.java。
 * 响应不含 passwordEnc（红线 R3）；前端表单 password 只提交不回显。
 */

export interface DataSourceItem {
  id: number
  name: string
  dbType: string
  jdbcUrl: string
  username: string
  status: string
  description: string
  createdAt: string | null
  updatedAt: string | null
}

/** 注册/更新请求；更新时 password 为空串表示不修改密码。 */
export interface DataSourceRequest {
  name: string
  dbType: string
  jdbcUrl: string
  username: string
  password?: string
  status?: string
  description?: string
}

export interface ConnectionTestResult {
  connected: boolean
  message: string
  tableCount: number | null
}

export interface RefreshResult {
  tableCount: number
  columnCount: number
  relationshipCount: number
  reindexNotified: boolean
  message: string
}

export interface TableMetadataItem {
  id: number
  dataSourceId: number
  tableName: string
  tableComment: string
  tableType: string
  rowCount: number | null
  collectedAt: string | null
}

export interface ColumnMetadataItem {
  id: number
  dataSourceId: number
  tableName: string
  columnName: string
  ordinal: number | null
  dataType: string
  nullable: string
  primaryKey: string
  columnComment: string
  sampleValues: string[]
}

export interface RelationshipItem {
  id: number
  dataSourceId: number
  sourceTable: string
  sourceColumn: string
  targetTable: string
  targetColumn: string
  relationType: string
}

export const DB_TYPE_OPTIONS = [
  { value: 'mysql', label: 'MySQL' },
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'h2', label: 'H2' },
  { value: 'oracle', label: 'Oracle' },
  { value: 'sqlserver', label: 'SQL Server' },
] as const

export const DATASOURCE_STATUS_OPTIONS = ['active', 'inactive'] as const
