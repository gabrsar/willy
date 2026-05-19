# Project Structure Prompt

User request:

```text
Vamos estruturar o projeto do willy.

1 - Crie um docs
2 - dentro de docs quero as pastas: ai, e decision_records
3 - dentro de ai, vão ficar os prompts, orgazniados por data YYYYMMDD-HHMMSS-nome.md
4 - dentro de decision_records ficarão documentos explicando decisões do projeto, mesmo modelo de nomenclatura.
5 - Crie um ai.md na base do projeto, com guidelines para agentes de IA seguirem as mesmas regras. Coloque as regras que estamos usando lá. - Teste para mudanças. - Bugs só podem ser corrigidos após um teste que reproduza. - Toda mudança e PR precisa de um arquivo no decision_record, e outras regras que vc julga importante.
6 - Ajusta o README.md para ficar: 1 - suscinto. 2 - fácil de clonar, buildar e executar o projeto. 3 - explica o projeto em um tweet.
7 - deps, põe todo o ambiente de dev dentro de um docker (um para windows, um para linux, um para mac), assim não precisa instalar nada localmente, só para rodar.
8 - crie um justfile (vamos jusar just por hora
```

