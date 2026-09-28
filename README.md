# OZ Propostas

Aplicação para registar pedidos de diagnóstico, rever a análise técnica, construir propostas, agendar visitas e acompanhar o envio.

## Tecnologias

- **Frontend:** Next.js App Router, React e TypeScript.
- **API:** Python 3.11+ com FastAPI.
- **Dados e autenticação:** Supabase Auth, Postgres, Storage privado e Row Level Security.
- **Análise:** OpenAI Responses API, chamada apenas pelo backend; sem chave de OpenAI, o sistema permite registo e análise básica.
- **Email:** Resend, apenas depois de a proposta ser aprovada.

Os ficheiros do sistema anterior estão guardados em [`legacy/`](legacy/). A aplicação nova usa as migrações de [`supabase/migrations/`](supabase/migrations/).

## Criar o projeto Supabase novo

1. Cria uma conta/projeto novos em [Supabase](https://supabase.com/dashboard). Guarda o project ref, URL, chave **publishable** e password da base de dados.
2. Na raiz do projeto, autentica o CLI, liga-o ao project ref novo e aplica as migrações:

   ```powershell
   npm install
   npx supabase login
   npx supabase link --project-ref kaeuqjqtknuuldstmcbd
   npx supabase db push --dry-run
   npx supabase db push
   ```

   `db push` aplica apenas as migrações pendentes. Confirma cuidadosamente o project ref antes de o ligar. Não uses `db reset --linked`, que apaga os dados remotos. A sequência cria o esquema, políticas RLS, catálogo de serviços, armazenamento privado e base de conhecimento inicial.
3. Em **Authentication → URL Configuration**, define o URL local `http://localhost:3000` para desenvolvimento. Cria o primeiro utilizador no próprio ecrã de registo da aplicação; o perfil é criado automaticamente.

O fluxo `link` e `db push` segue a [documentação oficial do Supabase](https://supabase.com/docs/guides/local-development/cli-workflows). O utilizador tem de criar a conta e o projeto Supabase: este repositório não guarda acesso à conta antiga.

## Configurar os ambientes

### Next.js

```powershell
Copy-Item apps/web/.env.local.example apps/web/.env.local
```

Preenche em `apps/web/.env.local`:

```env
NEXT_PUBLIC_SUPABASE_URL=https://kaeuqjqtknuuldstmcbd.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_5tRFQA9nh2nMSczWIGi7vQ_qpyAt1Fj
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Só a chave `sb_publishable_...` deve estar no browser. Não coloques uma chave `sb_secret_...` ou `service_role` em nenhuma variável `NEXT_PUBLIC_*`.

### Python / FastAPI

```powershell
Copy-Item apps/api/.env.example apps/api/.env
```

Preenche `apps/api/.env` com a mesma URL e chave publicável e, se pretenderes, as chaves de servidor:

```env
SUPABASE_URL=https://kaeuqjqtknuuldstmcbd.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_5tRFQA9nh2nMSczWIGi7vQ_qpyAt1Fj
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
RESEND_API_KEY=
EMAIL_FROM=
WEB_ORIGIN=http://localhost:3000
COMPANY_NAME=OZ Diagnóstico e Engenharia
COMPANY_ADDRESS=
COMPANY_EMAIL=
COMPANY_PHONE=
PROPOSAL_SIGNATORY=
PROPOSAL_PAYMENT_TERMS=
```

As chaves OpenAI e Resend só são lidas pela API Python. Os dados da empresa no fim do exemplo alimentam o cabeçalho e rodapé do PDF; `PROPOSAL_PAYMENT_TERMS` configura as condições comerciais fixas, e deixa a assinatura vazia até configurares o profissional responsável. Mantém os ficheiros `.env` locais e não os envies para GitHub. A API passa o token do utilizador ao Supabase para que a RLS continue a limitar cada operação.

## Executar localmente

Instala e arranca a API num terminal PowerShell:

```powershell
cd apps/api
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m uvicorn app.main:app --reload --port 8000
```

Noutro terminal, instala e arranca o Next.js:

```powershell
cd apps/web
npm install
npm run dev
```

Abre [http://localhost:3000](http://localhost:3000). A documentação interativa da API local fica em [http://localhost:8000/docs](http://localhost:8000/docs).

## Fluxo incluído

- Registo e início de sessão com Supabase Auth.
- Registo de pedidos a partir de texto, email colado ou anexo PDF/DOCX/XLSX/TXT/CSV/EML; os originais ficam num bucket privado e o texto extraído no pedido.
- Extração em Python do assunto, empresa cliente, NIF/NUIT, endereço, telefone, email, obra, localização, objetivo, âmbito e assinatura do remetente; a empresa cliente fica separada de quem enviou o email.
- Extração estruturada por OpenAI com alternativa por regras sem chave de IA e indicação dos campos em falta.
- Revisão e gravação dos dados extraídos, estado do pedido, agenda de visitas e acesso aos anexos privados.
- Criação numerada de proposta, catálogo de serviços, quantidades, preços, IVA e totais.
- Geração e transferência de PDF, versões imutáveis da proposta e estados de aprovação/envio.
- Sugestões de serviços elétricos a partir do âmbito do email, com preço zero até validação técnica.
- Mapeamento preliminar Python de patologias da base técnica para causas, ensaios e soluções codificados; quando a chave OpenAI está configurada, a seleção de candidatos é refinada por IA e limitada aos códigos existentes.
- Geração de proposta PDF em seis secções, inspirada na estrutura do documento de referência: objeto, considerações prévias, condições técnicas e ensaios, mapeamento de patologias, honorários e condições comerciais.
- Biblioteca de propostas: pesquisa de propostas geradas, carregamento de propostas antigas e consulta de referências semelhantes. Os ficheiros carregados ficam privados e não são partilhados entre utilizadores.
- Envio manual pelo Resend após aprovação, com o PDF gerado anexado automaticamente.
- Consulta da base técnica de patologias, causas, ensaios e soluções.

## Limites a conhecer

- PDF digitalizado ainda requer OCR; o sistema informa quando não consegue extrair texto.
- A primeira migração cria dados com isolamento RLS por utilizador. As propostas e clientes não são automaticamente partilhados entre contas distintas.
- As referências de diagnóstico herdadas do sistema anterior precisam de validação de um engenheiro antes de uso técnico.
- A percentagem de correspondência técnica mede aderência textual ao catálogo, não a probabilidade de uma patologia. Causas e soluções são hipóteses para confirmação pelo engenheiro.
- A base instalada contém códigos de patologias estruturais e de edifícios, mas ainda não tem uma taxonomia elétrica codificada; pedidos elétricos não recebem códigos estruturais por aproximação.
- Assinatura profissional e dados da empresa no PDF são configuráveis no `.env`; não é reproduzida a assinatura manuscrita do documento de referência.
- Os textos de validade, execução, pagamento e exclusões ficam indicados para validação humana no documento final.
