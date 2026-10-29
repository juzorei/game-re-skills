# Ready-to-post drafts

Copy-paste material for promoting game-re-skills. Russian drafts below; English
versions in POSTS.en.md (write on demand).

## r/pathofexile_dev, r/gamedev (RU/EN hubs), r/ReverseEngineering

> Сделал набор скиллов для ИИ-агентов под реверс игр: https://github.com/juzorei/game-re-skills
>
> Контекст: Claude Code / Codex / Cursor умеют читать код, но когда речь про чужой процесс — они начинают угадывать оффсеты и хардкодить адреса, которые ломаются на первом же патче. Я собрал 6 скиллов, которые ведут агента по рабочему процессу: значение в Cheat Engine → цепочка указателей → сигнатура, переживающая патчи → файл оффсетов → ридер на Python с тестами → что делать, когда игра обновилась.
>
> В комплекте sigtool (CLI без зависимостей): проверяет, что сигнатура матчится ровно один раз, резолвит [rip+x], сравнивает файл сигнатур по нескольким сборкам игры и проходит цепочки указателей. `sigtool demo` создаёт два синтетических билда, можно пощупать без игры.
>
> Скоуп: одиночные/офлайн-игры, моддинг. Без обхода анти-чита.
>
> Установка: `npx skills add juzorei/game-re-skills`

##HN (news.ycombinator.com — Show HN)

> Show HN: Agent skills for game reverse engineering + a CLI that verifies them
> https://github.com/juzorei/game-re-skills
>
> Six skills that walk a coding agent through game modding reverse engineering:
> Cheat Engine pointer chains, AOB signatures that survive patches (auto-wildcards
> relocatable x86-64 operands, keeps struct displacements), Unreal GWorld/GObjects/GNames
> via Dumper-7/UE4SS, Unity IL2CPP dump.cs, a read-only memory reader template tested
> against fake memory, and patch-day triage. sigtool checks every result: one match,
> resolved RVA, field offsets read straight from instructions, cross-build regression.
> Single-player/offline/modding only (SCOPE.md). `npx skills add juzorei/game-re-skills`,
> `sigtool demo` to try in 30 seconds.

##Telegram (RU gameautomation/modding channels)

> 🎮 Запилил game-re-skills — набор скиллов для ИИ-агентов (Claude Code, Codex, Cursor)
> под реверс игр: pointer chains через Cheat Engine, AOB-сигнатуры под патчи, оффсеты
> Unreal (GWorld/GObjects/GNames) и Unity IL2CPP, шаблон read-only ридера памяти на
> Python и триаж после апдейта игры.
>
> Изюминка: sigtool — CLI, который проверяет работу агента (сигнатура матчится ровно
> один раз, оффсет поля читается из инструкции, регресс по билдам).
>
> npx skills add juzorei/game-re-skills
> https://github.com/juzorei/game-re-skills

##dev.to / Habr (draft outline)

1. Hook: «агенты врут про оффсеты — я заставил их проверять»
2. Problem: agent guesses addresses, breaks on patches, no feedback loop
3. Solution: skills = process, sigtool = verification (демо-вывод из README)
4. Technical meat: x64 length decoder для auto-wildcards; почему struct displacements
   НЕ вайлдкардятся; chain semantics как в CE
5. Scope honesty: offline only, no anti-cheat
6. CTA: npx skills add, sigtool demo
