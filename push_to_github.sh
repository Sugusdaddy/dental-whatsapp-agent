#!/bin/bash
# ══════════════════════════════════════════════
# Sube el proyecto a GitHub en un comando
# Uso: bash push_to_github.sh TU_USUARIO TU_REPO
# Ejemplo: bash push_to_github.sh juangarcia dental-agent
# ══════════════════════════════════════════════

set -e

GITHUB_USER=${1:?"Falta usuario de GitHub. Uso: bash push_to_github.sh USUARIO REPO"}
GITHUB_REPO=${2:?"Falta nombre del repo. Uso: bash push_to_github.sh USUARIO REPO"}

echo ""
echo "Subiendo a https://github.com/$GITHUB_USER/$GITHUB_REPO"
echo ""

# 1. Inicializar git si no existe
if [ ! -d ".git" ]; then
  git init
  echo "✓ git init"
fi

# 2. Configurar remote
if git remote get-url origin &>/dev/null; then
  git remote set-url origin "https://github.com/$GITHUB_USER/$GITHUB_REPO.git"
else
  git remote add origin "https://github.com/$GITHUB_USER/$GITHUB_REPO.git"
fi
echo "✓ remote configurado"

# 3. Añadir todos los archivos
git add .
echo "✓ archivos añadidos"

# 4. Commit inicial
git commit -m "feat: agente dental WhatsApp MVP

- LangGraph + Claude claude-sonnet-4-20250514
- 7 tools: citas, confirmación, cancelación, escalación
- Webhook FastAPI multi-tenant
- Scheduler recordatorios 48h/2h y reporte semanal
- 51 tests passing (unitarios + webhook + scheduler)
- Schema PostgreSQL con índices y triggers
- Dockerfile para Railway/Render" 2>/dev/null || echo "✓ nada nuevo que commitear"

# 5. Push
git branch -M main
git push -u origin main

echo ""
echo "✓ Subido correctamente"
echo "  https://github.com/$GITHUB_USER/$GITHUB_REPO"
