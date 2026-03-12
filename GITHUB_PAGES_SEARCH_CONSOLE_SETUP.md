# GitHub Pages + Search Console Setup

현재 저장소 `sheryloe/grid-crop-image` 기준으로 GitHub Pages 배포, GitHub repo 메타데이터, Google Search Console 검색 노출 세팅을 명령어 기준으로 정리한 문서입니다.

## 현재 기준 URL

- GitHub repository: `https://github.com/sheryloe/grid-crop-image`
- GitHub Pages site: `https://sheryloe.github.io/grid-crop-image/`
- robots.txt: `https://sheryloe.github.io/grid-crop-image/robots.txt`
- sitemap.xml: `https://sheryloe.github.io/grid-crop-image/sitemap.xml`
- Search Console verification file: `https://sheryloe.github.io/grid-crop-image/googleb146312c1195390f.html`

## 현재 구조

이제 Pages/SEO 관련 내용은 아래처럼 정리돼 있습니다.

- `config/pages-seo.json`: 설명, 키워드, repo description, homepage, topics, verification 파일 정보
- `templates/index.template.html`: Pages 랜딩 페이지 템플릿
- `scripts/generate_pages_assets.py`: 루트 공개 파일 생성
- `scripts/update_github_repo_metadata.ps1`: GitHub repo 메타데이터 갱신
- `scripts/request_search_console_verification.ps1`: Search Console HTML 검증 파일 생성
- `scripts/submit_search_console.ps1`: Search Console 속성 추가 및 sitemap 제출

루트에 있는 아래 파일들은 생성 결과물입니다.

- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

## 1. Pages 공개 파일 다시 만들기

설명, 키워드, 제목, canonical URL, repo URL, Search Console 관련 설정은 `config/pages-seo.json`에서 관리합니다.

설정을 수정한 뒤 아래 명령으로 루트 공개 파일을 다시 만듭니다.

```powershell
python scripts/generate_pages_assets.py
```

생성 대상:

- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

## 2. GitHub repo description, homepage, topics 갱신

이 단계는 GitHub 토큰이 필요합니다.

필요 환경 변수:

- `GITHUB_TOKEN`

설정 가능한 항목:

- Repository description
- Repository homepage
- Repository topics
- GitHub Pages source 요청

실행 명령:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update_github_repo_metadata.ps1
```

## 3. Search Console HTML 검증 파일 새로 받기

이미 검증 파일이 있다면 이 단계는 건너뛰어도 됩니다. 새 URL이나 새 property를 잡아야 할 때만 사용하면 됩니다.

필요 환경 변수:

- `GOOGLE_SITEVERIFICATION_TOKEN`

대체 가능:

- `GOOGLE_OAUTH_TOKEN`

실행 명령:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\request_search_console_verification.ps1
```

이 스크립트는 Google에서 받은 HTML 파일 이름을 그대로 저장소 루트에 생성합니다. 그 다음 `git add`, `commit`, `push`를 하면 됩니다.

## 4. Search Console 속성 추가 및 sitemap 제출

GitHub Pages 프로젝트 사이트는 이 저장소 기준으로 다음 URL 하위 경로에 게시됩니다.

```text
https://sheryloe.github.io/grid-crop-image/
```

따라서 Search Console에서는 아래처럼 추가하는 것이 맞습니다.

- 권장 속성: `URL-prefix property`
- 속성 값: `https://sheryloe.github.io/grid-crop-image/`

필요 환경 변수:

- `GOOGLE_OAUTH_TOKEN`

실행 명령:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\submit_search_console.ps1
```

이 스크립트는 아래 작업을 수행합니다.

- 검증 파일 URL 응답 확인
- Search Console site add request
- sitemap submit request

## 5. 상태 확인 명령어

```bat
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/robots.txt
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/sitemap.xml
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/googleb146312c1195390f.html
```

내용까지 확인:

```bat
curl.exe --ssl-no-revoke https://sheryloe.github.io/grid-crop-image/robots.txt
curl.exe --ssl-no-revoke https://sheryloe.github.io/grid-crop-image/sitemap.xml
curl.exe --ssl-no-revoke https://sheryloe.github.io/grid-crop-image/googleb146312c1195390f.html
```

## 6. 직접 API를 때리고 싶을 때

### GitHub Pages 정보 조회

`gh`:

```bat
gh api repos/sheryloe/grid-crop-image/pages
```

`curl`:

```bat
curl.exe -L -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2022-11-28" https://api.github.com/repos/sheryloe/grid-crop-image/pages
```

### GitHub Pages source를 main 루트로 설정

`gh`:

```bat
gh api -X PUT repos/sheryloe/grid-crop-image/pages -f source[branch]=main -f source[path]=/
```

`curl`:

```bat
curl.exe -L -X PUT -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2022-11-28" https://api.github.com/repos/sheryloe/grid-crop-image/pages -d "{\"source\":{\"branch\":\"main\",\"path\":\"/\"}}"
```

### GitHub repo description/homepage 업데이트

```bat
curl.exe -L -X PATCH -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2022-11-28" https://api.github.com/repos/sheryloe/grid-crop-image -d "{\"description\":\"Windows image crop and split tool for screenshots, clipboard paste, JSON crop layouts, and sequential export.\",\"homepage\":\"https://sheryloe.github.io/grid-crop-image/\"}"
```

### GitHub repo topics 업데이트

```bat
curl.exe -L -X PUT -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2022-11-28" https://api.github.com/repos/sheryloe/grid-crop-image/topics -d "{\"names\":[\"desktop-app\",\"image-cropping\",\"image-processing\",\"pillow\",\"pyinstaller\",\"python\",\"search-console\",\"seo\",\"tkinter\",\"windows\"]}"
```

### Search Console 속성 추가

```bat
curl.exe -L -X PUT -H "Authorization: Bearer %GOOGLE_OAUTH_TOKEN%" "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2F"
```

### sitemap 제출

```bat
curl.exe -L -X PUT -H "Authorization: Bearer %GOOGLE_OAUTH_TOKEN%" "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2F/sitemaps/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2Fsitemap.xml"
```

### Search Console HTML 파일 토큰 발급

```bat
curl.exe -L -X POST -H "Authorization: Bearer %GOOGLE_SITEVERIFICATION_TOKEN%" -H "Content-Type: application/json" https://www.googleapis.com/siteVerification/v1/token -d "{\"site\":{\"type\":\"SITE\",\"identifier\":\"https://sheryloe.github.io/grid-crop-image/\"},\"verificationMethod\":\"FILE\"}"
```

## 7. 배포 루틴

실제로는 아래 순서만 지키면 됩니다.

1. `config/pages-seo.json` 수정
2. `python scripts/generate_pages_assets.py`
3. 필요하면 `scripts/update_github_repo_metadata.ps1` 실행
4. 필요하면 `scripts/request_search_console_verification.ps1` 실행
5. `git add` 후 커밋
6. `git push origin main`
7. `scripts/submit_search_console.ps1` 또는 Search Console UI에서 검증/제출

## 현재 환경 참고

- 현재 로컬 환경에는 `gh` CLI가 설치돼 있지 않습니다.
- 그래서 이 저장소는 `curl` 또는 PowerShell 스크립트 기준으로 운영하는 것이 가장 현실적입니다.
- GitHub Pages 루트 URL과 검증 파일 URL은 외부에서 200 응답으로 접근 가능한 상태여야 합니다.
