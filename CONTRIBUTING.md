# Guia de Contribucion y Convenciones Git

## Flujo de Trabajo con `uv`

1. Sincronizar dependencias:
   ```powershell
   uv sync --extra dev
   ```
2. Ejecutar pruebas antes de cualquier commit:
   ```powershell
   uv run pytest -v
   ```

## Convencion de Commits y Notas Git

Usar prefijos semanticos en espanol:
- `feat(modulo): descripcion breve`
- `fix(modulo): descripcion breve`
- `docs: descripcion breve`
- `build: descripcion breve`

Para dejar contexto tecnico auditable en el historial sin ensuciar el titulo del commit, adjuntar una nota Git:
```powershell
git notes add -m "Verificacion: pytest 11/11 OK; probado en Windows 11 Build 26200." HEAD
```
Para inspeccionar el historial con notas:
```powershell
git log --show-notes --oneline
```
