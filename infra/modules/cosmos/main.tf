# Cosmos DB for NoSQL, serverless, with vector search (D2, D9). Terraform owns the database and
# both containers on Azure: data-plane RBAC can't create them (D9).
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

resource "azurerm_cosmosdb_account" "this" {
  #checkov:skip=CKV_AZURE_99:No IP filter: the Flex app has no fixed egress IPs without VNet integration; Entra-only access (D15)
  #checkov:skip=CKV_AZURE_101:Public network access needed for the same reason (D15)
  #checkov:skip=CKV_AZURE_140:Checks the deprecated local_authentication_disabled; local_authentication_enabled = false below (Conftest enforces it)
  #checkov:skip=CKV_AZURE_100:CMK not used for a disposable lab account; Microsoft-managed keys
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  capabilities {
    name = "EnableServerless"
  }

  capabilities {
    name = "EnableNoSQLVectorSearch"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  local_authentication_enabled       = false # Entra ID + Cosmos data-plane RBAC only (D6)
  access_key_metadata_writes_enabled = false # no control-plane changes through account keys
  public_network_access_enabled      = true  # D15
  minimal_tls_version                = "Tls12"

  backup {
    type = "Continuous"
    tier = "Continuous7Days"
  }

  tags = var.tags
}

resource "azurerm_cosmosdb_sql_database" "this" {
  name                = var.database_name
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
}

# Triage records: every access is a point read/write by ticket id (D11).
resource "azurerm_cosmosdb_sql_container" "triage" {
  name                = "triage"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
  database_name       = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths = ["/id"]
}

# KB + resolved tickets with the DiskANN vector index. azurerm 4.x has no vector policy on
# azurerm_cosmosdb_sql_container and Cosmos can't add one to an existing container, so this container
# is an ARM template deployment (D17). The policy mirrors triage.cosmos.kb_policies();
# tests/unit/test_infra_contract.py keeps the two identical.
resource "azurerm_resource_group_template_deployment" "knowledge" {
  name                = "cosmos-knowledge-container"
  resource_group_name = var.resource_group_name
  deployment_mode     = "Incremental"
  template_content    = file("${path.module}/knowledge-container.json")
  parameters_content = jsonencode({
    accountName   = { value = azurerm_cosmosdb_account.this.name }
    databaseName  = { value = azurerm_cosmosdb_sql_database.this.name }
    containerName = { value = "knowledge" }
    dimensions    = { value = var.embedding_dimensions }
  })
}

resource "azurerm_monitor_diagnostic_setting" "account" {
  count                          = var.diagnostics_enabled ? 1 : 0
  name                           = "diag-to-law"
  target_resource_id             = azurerm_cosmosdb_account.this.id
  log_analytics_workspace_id     = var.log_analytics_workspace_id
  log_analytics_destination_type = "Dedicated" # resource-specific CDB* tables

  enabled_log {
    category_group = "allLogs"
  }
}
