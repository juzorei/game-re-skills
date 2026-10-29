# game-re-skills

[English](README.md) | [Русский](README.ru.md)

[![CI](https://github.com/juzorei/game-re-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/juzorei/game-re-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/juzorei/game-re-skills)](LICENSE)
[![Release](https://img.shields.io/github/v/release/juzorei/game-re-skills)](https://github.com/juzorei/game-re-skills/releases)

Скиллы для ИИ-агентов по реверсу игр и небольшая CLI-утилита, которая проверяет работу агента.

```text
$ npx skills add juzorei/game-re-skills
$ pip install game-re-sigtool
$ sigtool demo && cd sigtool-demo
$ sigtool check signatures.toml game-1.0.exe game-1.1.exe
== game-1.0.exe
  ok   GWorld           matches 1  rva 0x1100  rel -> rva 0x3040 (va 0x140003040, offset 0xc40)
  ok   HealthOffset     matches 1  rva 0x1200  read = 0x1a8 (424)
  ok   OldHealthOffset  matches 1  rva 0x1200
== game-1.1.exe
  ok   GWorld           matches 1  rva 0x1180  rel -> rva 0x3040 (va 0x140003040, offset 0xc40)
  ok   HealthOffset     matches 1  rva 0x1200  read = 0x1b0 (432)
  FAIL OldHealthOffset  matches 0
5/6 passed
```

Игру запатчили: код переехал, а поле здоровья сместилось с `0x1A8` на `0x1B0`. Сигнатуры с масками это пережили и теперь сообщают новые значения. Та, что захардкодила оффсет, сломалась — и именно это лучше узнать до того, как это заметят твои пользователи.

Агенты уже много знают про x64, Cheat Engine и устройство Unreal. Им не хватает процесса: они угадывают оффсеты, хардкодят адреса, которые ломаются на следующем патче, и пишут «должно работать», ничего не проверив. Эти скиллы дают Claude Code, Codex, Cursor, ZCode и другим агентам пошаговый процесс для каждой задачи, и каждый скилл заканчивается результатом, проверенным через `sigtool`.

## Скиллы

| Скилл | Когда нужен |
|---|---|
| [cheat-engine-pointer-chains](skills/cheat-engine-pointer-chains) | Значение видно на экране (здоровье, золото, позиция), нужна цепочка указателей, которая переживает перезапуск. |
| [aob-signatures](skills/aob-signatures) | Адрес меняется каждое обновление и нужна сигнатура, которая не меняется. Или нужно вычислить `[rip+x]` и оффсеты полей из кода. |
| [unreal-sdk-offsets](skills/unreal-sdk-offsets) | Игра на UE4/UE5: найти GObjects, GNames и GWorld, снять SDK через Dumper-7 или UE4SS и дойти до локального игрока. |
| [unity-il2cpp-offsets](skills/unity-il2cpp-offsets) | Игра на Unity IL2CPP: сдампить `GameAssembly.dll` и `global-metadata.dat`, прочитать `dump.cs`, найти статические экземпляры. |
| [external-memory-reader](skills/external-memory-reader) | Оффсеты есть, нужен ридер на Python только для чтения: быстрый, с тестами без запуска игры и без тихих нулей. |
| [game-patch-recovery](skills/game-patch-recovery) | Игра обновилась, и мод, ридер или трейнер сломался. Найти, что сдвинулось, и починить. |

Скиллы ссылаются друг на друга. Обычный путь: `unreal-sdk-offsets` находит GWorld, `aob-signatures` делает его устойчивым к патчам, `external-memory-reader` его читает, а `game-patch-recovery` подхватывает в день обновления.

## sigtool

[`tools/sigtool`](tools/sigtool) — офлайн-утилита (Python 3.11+, без зависимостей), которой скиллы проверяют результат. Она ищет паттерны (синтаксис IDA/CE, полубайтовые маски), вычисляет цели RIP-relative адресации, генерирует кратчайшую уникальную сигнатуру с замаскированными перемещаемыми операндами, прогоняет файл сигнатур по нескольким сборкам и проходит цепочки указателей в стиле Cheat Engine (Windows, только чтение). Попробовать на синтетических сборках: `sigtool demo`.

## Установка

Через [skills CLI](https://github.com/vercel-labs/skills), для любого поддерживаемого агента:

```bash
npx skills add juzorei/game-re-skills
```

Как плагин Claude Code:

```text
/plugin marketplace add juzorei/game-re-skills
/plugin install game-re-skills@game-re-skills
```

Вручную: скопировать папки из `skills/` в каталог скиллов агента (`~/.claude/skills/`, `~/.agents/skills/`, `.codex/skills/` и так далее).

Затем sigtool:

```bash
pip install game-re-sigtool
```

## Рамки

Скиллы предназначены для одиночных и офлайн-игр, моддинга, совместимости, исследований и собственных приватных серверов. Они не помогают обходить античит, скрываться от детекта или читерить в онлайн-мультиплеере, и агент прямо об этом скажет. Подробнее в [SCOPE.md](SCOPE.md).

## Как помочь

Самое ценное — поправки от тех, кто сталкивался с этим на реальных играх: другая раскладка структуры на какой-то версии движка, изменившийся флаг утилиты, шаг, который не сработал. Подробнее в [CONTRIBUTING.md](CONTRIBUTING.md).

Лицензия MIT.
