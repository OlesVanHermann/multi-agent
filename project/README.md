# Project Directory

Ce dossier est destiné à contenir votre projet (code source).

## Usage

### Option 1 : Cloner votre projet ici

```bash
cd project
git clone https://github.com/your/project.git .
```

### Option 2 : Créer un nouveau projet

```bash
cd project
mkdir my-project
cd my-project
git init
```

### Option 3 : Lien symbolique

```bash
mkdir -p removed && mv project removed/project-$(date +%s)
ln -s /path/to/your/existing/project project
```

## Configuration

L'Architect (900) configurera automatiquement les chemins dans `project-config.md` pour pointer vers ce dossier.

## Note

Ce dossier est ignoré par git (`.gitignore`) sauf ce README.
