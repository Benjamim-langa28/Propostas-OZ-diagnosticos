# OZ Intelligent Proposal

Aplicação web para registar pedidos de diagnóstico e ensaios, extrair informação de emails/anexos, rever o âmbito com um engenheiro, gerar propostas OZ e acompanhar o respetivo estado.

## Estado da aplicação

- `index.html` — autenticação Supabase; dashboard com pesquisa, prazos e visitas; análise OpenAI estruturada (com regras locais como fallback); importação de MQT `.xlsx`; extração de texto PDF/DOCX/TXT; checklist, patologias, preços e âmbito editáveis; geração PDF/Word e MQT preenchido; rascunhos `mailto:`; estados de proposta e histórico.
- `003_knowledge_base.sql` — dados da base de conhecimento técnica apresentados no ecrã Base de conhecimento.
- `supabase/001_schema.sql` — esquema principal, catálogo e contadores.
- `supabase/002_oz_drafts.sql` — tabela JSON temporária de propostas, com RLS por proprietário.
- `supabase/003_oz_drafts_delete.sql` — política de eliminação necessária ao botão Eliminar do dashboard.
- `supabase/functions/analyse-request/index.ts` — função autenticada que chama a OpenAI Responses API e devolve campos em JSON Schema. A chave da OpenAI existe apenas nos secrets da função.

## Configuração e publicação

1. `index.html` já contém a URL do projeto e a chave publicável Supabase. Essa chave é própria do cliente web; nunca substituir por uma chave `service_role`.
2. Como as tabelas `001_schema.sql` e `002_oz_drafts.sql` já foram executadas, execute agora `supabase/003_oz_drafts_delete.sql` no SQL Editor para autorizar a eliminação de rascunhos próprios.
3. Crie utilizadores em **Supabase → Authentication → Users**. Para os contadores do esquema principal, cada utilizador também precisa de um registo em `profiles` com um papel adequado (`ENGINEER`, `MANAGER` ou `ADMIN`). No SQL Editor, substitua os dois valores de exemplo pelo UUID Auth e nome:

   ```sql
   insert into public.profiles (id, full_name, role)
   values ('<UUID_DO_UTILIZADOR_AUTH>', '<NOME>', 'ENGINEER')
   on conflict (id) do update
   set full_name = excluded.full_name, role = excluded.role;
   ```
4. Defina `OPENAI_API_KEY` nos secrets das Edge Functions do Supabase. Opcionalmente, defina `OPENAI_MODEL`; o padrão é `gpt-4.1-mini`. Não guardar esta chave no HTML nem no repositório.
5. Com Node.js disponível, autentique o Supabase CLI e publique a função na raiz deste projeto:

   ```powershell
   npx supabase login
   npx supabase functions deploy analyse-request --project-ref jvmtzprcghzixqrakefm
   ```

   `supabase/config.toml` exige JWT válido. O utilizador tem de iniciar sessão para chamar a função.

## Limites operacionais

- O browser extrai texto de PDF, DOCX e TXT. PDF digitalizado requer OCR e não é processado. MQT `.xlsx` fica limitado a 3 MB.
- A OpenAI só sugere campos e categorias; o engenheiro continua responsável por validar o âmbito e preços. A chave da API deve estar ativa e com acesso ao modelo configurado.
- Emails abrem no programa de email do utilizador como rascunhos. O sistema só marca a proposta enviada quando alguém usa **Marcar como enviada**; não envia anexos automaticamente.
- Propostas são guardadas na tabela temporária `oz_drafts` como JSON completo. O esquema relacional principal já existe, mas a migração automática para `proposal_requests`, `proposals` e `proposal_items` ainda não foi implementada.
- Os textos de pagamento, prazos e exclusões permanecem por validar pelo engenheiro e aparecem como "A definir pelo engenheiro".
