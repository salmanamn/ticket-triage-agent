output "account_id" {
  value = azurerm_cosmosdb_account.this.id
}

output "account_name" {
  value = azurerm_cosmosdb_account.this.name
}

output "endpoint" {
  value = azurerm_cosmosdb_account.this.endpoint
}

output "database_name" {
  value = azurerm_cosmosdb_sql_database.this.name
}

output "triage_container_name" {
  value = azurerm_cosmosdb_sql_container.triage.name
}

output "knowledge_container_name" {
  value = jsondecode(azurerm_resource_group_template_deployment.knowledge.output_content).containerName.value
}
