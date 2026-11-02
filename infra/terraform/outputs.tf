output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "api_health_url" {
  value = "http://${aws_lb.api.dns_name}/health"
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "task_definition" {
  value = aws_ecs_task_definition.api.family
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}
