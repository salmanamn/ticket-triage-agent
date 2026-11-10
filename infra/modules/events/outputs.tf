output "topic_id" {
  value = azurerm_eventgrid_topic.this.id
}

output "topic_endpoint" {
  value = azurerm_eventgrid_topic.this.endpoint
}
