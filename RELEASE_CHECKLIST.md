# RELEASE_CHECKLIST.md

## Пошаговая публикация ChatList

### 1. Перед выпуском
- Обнови `version.py`
- Проверь, что имя тега будет вида `vX.Y.Z`
- Убедись, что `ChatListApp.spec`, `ChatListInstaller.iss` и `build_installer.py` соответствуют текущей версии
- Проверь локальный запуск приложения

### 2. Локальная сборка
- Собери `exe`:

```powershell
python -m PyInstaller --noconfirm --distpath dist_new --workpath build_new ChatListApp.spec
```

- Собери установщик:

```powershell
python build_installer.py
```

- Проверь наличие файлов:
  - `dist_new/ChatListApp.exe`
  - `release/ChatListApp_Setup_<версия>.exe`

### 3. Обновление GitHub Pages
- Открой `docs/config.js`
- Обнови:
  - `version`
  - `releaseTag`
  - при необходимости `repositoryUrl`
- Убедись, что лендинг в `docs/index.html` всё ещё соответствует текущему процессу установки

### 4. Коммит и тег
- Сохрани изменения в git
- Создай коммит
- Создай тег:

```powershell
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

### 5. Публикация GitHub Release
- Если используешь workflow `.github/workflows/release.yml`, дождись завершения job
- Если публикуешь вручную:
  - открой `GitHub -> Releases -> Draft a new release`
  - выбери тег `vX.Y.Z`
  - вставь заметки из `RELEASE_TEMPLATE.md`
  - загрузи:
    - `ChatListApp_Setup_<версия>.exe`
    - `ChatListApp.exe`

### 6. Проверка после публикации
- Открой страницу `GitHub Release`
- Проверь, что скачивание установщика работает
- Открой `GitHub Pages`
- Проверь кнопки:
  - `Скачать установщик`
  - `Открыть GitHub Release`

### 7. Что проверить вручную
- Устанавливается ли программа из инсталлятора
- Создаётся ли база в `LocalAppData\ChatList`
- Читается ли `.env.local`
- Проходит ли `Тест подключения` для моделей с валидными ключами

