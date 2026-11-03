resource "aws_ecr_repository" "api" {
  name         = "${var.project}-api"
  force_delete = true # Lets terraform destroy remove pushed images.
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the two newest images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 2
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
  retention_in_days = 7
}

resource "aws_iam_role" "task_execution" {
  name_prefix = "${var.project}-exec-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "read_secrets" {
  name = "read-app-secrets"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "secretsmanager:GetSecretValue"
      Resource = [
        aws_secretsmanager_secret.database_url.arn,
        aws_secretsmanager_secret.jwt.arn,
      ]
    }]
  })
}

resource "aws_ecs_cluster" "main" {
  name = var.project
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "3072"
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    # CORS_ALLOWED_ORIGINS is deliberately unset (no browser origin
    # allowed): the frontend is served from the same CloudFront origin as
    # the API, so the browser never makes a cross-origin call.
    environment = [
      { name = "APP_ENV", value = "production" },
      { name = "DEV_AUTH_BYPASS", value = "false" },
      { name = "OAUTH_AUDIENCE", value = var.oauth_audience },
    ]
    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
      { name = "APP_JWT_SECRET", valueFrom = aws_secretsmanager_secret.jwt.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_lb" "api" {
  name               = "${var.project}-api"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # Must outlast CloudFront's origin response timeout: during a long upload
  # no bytes flow until the API answers, and the load balancer would
  # otherwise cut the connection first. (The container's keep-alive, set in
  # docker/api/Dockerfile, is longer again, as AWS recommends.)
  idle_timeout = var.api_origin_read_timeout + 10
}

resource "aws_lb_target_group" "api" {
  name_prefix = "crag-"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  # Anything that doesn't match a rule below is refused. Health checks go
  # from the load balancer to the containers and aren't affected.
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"detail\":\"Forbidden\"}"
      status_code  = "403"
    }
  }
}

# Only requests carrying this distribution's secret origin header are
# forwarded, so other CloudFront distributions (which share the same
# origin-facing IP ranges) can't use the load balancer.
resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    http_header {
      http_header_name = local.origin_verify_header
      values           = [random_password.origin_verify.result]
    }
  }
}

# Temporary direct access for debugging, only while debug_allowed_cidrs is set
# AND debug_bypass_origin_check is true.
resource "aws_lb_listener_rule" "debug_ips" {
  count        = length(var.debug_allowed_cidrs) > 0 && var.debug_bypass_origin_check ? 1 : 0
  listener_arn = aws_lb_listener.http.arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    source_ip {
      values = var.debug_allowed_cidrs
    }
  }
}

resource "aws_ecs_service" "api" {
  name                              = "${var.project}-api"
  cluster                           = aws_ecs_cluster.main.id
  task_definition                   = aws_ecs_task_definition.api.arn
  launch_type                       = "FARGATE"
  desired_count                     = var.desired_count
  health_check_grace_period_seconds = 120

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront, aws_iam_role_policy_attachment.task_execution]
}
