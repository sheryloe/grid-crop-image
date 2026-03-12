# GitHub Pages + Search Console Setup

현재 저장소 `sheryloe/grid-crop-image` 기준으로 GitHub Pages 배포와 Google Search Console 검색 노출 세팅을 정리한 문서입니다.

## 현재 기준 URL

- GitHub repository: `https://github.com/sheryloe/grid-crop-image`
- GitHub Pages site: `https://sheryloe.github.io/grid-crop-image/`
- robots.txt: `https://sheryloe.github.io/grid-crop-image/robots.txt`
- sitemap.xml: `https://sheryloe.github.io/grid-crop-image/sitemap.xml`
- Search Console verification file: `https://sheryloe.github.io/grid-crop-image/googleb146312c1195390f.html`

## 이번에 저장소에 배치한 파일

- `index.html`: GitHub Pages용 SEO 랜딩 페이지
- `robots.txt`: 크롤러 허용 및 sitemap 위치 선언
- `sitemap.xml`: 현재 canonical URL 기준 XML sitemap
- `.nojekyll`: GitHub Pages에서 Jekyll 처리 없이 루트 파일 그대로 배포
- `googleb146312c1195390f.html`: Search Console HTML 파일 검증용 파일

## Search Console 속성은 이렇게 잡는 것이 맞습니다

GitHub Pages 프로젝트 사이트는 이 저장소 기준으로 다음 URL 하위 경로에 게시됩니다.

```text
https://sheryloe.github.io/grid-crop-image/
```

따라서 Search Console에서는 아래처럼 추가하는 것이 맞습니다.

- 권장 속성: `URL-prefix property`
- 속성 값: `https://sheryloe.github.io/grid-crop-image/`

`Domain property`는 DNS 검증이 필요하고, `github.io` 프로젝트 사이트에서는 보통 `URL-prefix property`가 가장 간단합니다.

## HTML 파일 검증 규칙

HTML 파일 검증을 쓸 때는 아래 규칙을 지켜야 합니다.

- 검증 파일은 사이트 루트에 있어야 합니다.
- 파일명과 파일 내용은 Google이 준 값을 그대로 유지해야 합니다.
- 브라우저에서 직접 열렸을 때 200 응답으로 보여야 합니다.

현재 이 저장소는 아래 파일이 이미 루트에 있습니다.

```text
googleb146312c1195390f.html
```

파일 내용:

```text
google-site-verification: googleb146312c1195390f.html
```

만약 Search Console에서 새 HTML 파일을 다시 발급받으면, Google이 준 파일명을 그대로 저장소 루트에 추가하고 커밋/푸시하면 됩니다.

## Pages 상태 확인 명령어

```bat
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/robots.txt
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/sitemap.xml
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/googleb146312c1195390f.html
```

내용 확인:

```bat
curl.exe --ssl-no-revoke https://sheryloe.github.io/grid-crop-image/robots.txt
curl.exe --ssl-no-revoke https://sheryloe.github.io/grid-crop-image/sitemap.xml
curl.exe --ssl-no-revoke https://sheryloe.github.io/grid-crop-image/googleb146312c1195390f.html
```

## GitHub Pages API 자동화 명령어

### 1. Pages 정보 조회

`gh`:

```bat
gh api repos/sheryloe/grid-crop-image/pages
```

`curl`:

```bat
curl.exe -L -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2026-03-10" https://api.github.com/repos/sheryloe/grid-crop-image/pages
```

### 2. Pages 소스 경로를 `main` 브랜치 루트로 맞추기

`gh`:

```bat
gh api -X PUT repos/sheryloe/grid-crop-image/pages -f source[branch]=main -f source[path]=/
```

`curl`:

```bat
curl.exe -L -X PUT -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2026-03-10" https://api.github.com/repos/sheryloe/grid-crop-image/pages -d "{\"source\":{\"branch\":\"main\",\"path\":\"/\"}}"
```

### 3. Pages 재빌드 요청

`gh`:

```bat
gh api -X POST repos/sheryloe/grid-crop-image/pages/builds
```

`curl`:

```bat
curl.exe -L -X POST -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2026-03-10" https://api.github.com/repos/sheryloe/grid-crop-image/pages/builds
```

## Search Console API 자동화 명령어

아래 예시는 Google OAuth Access Token이 이미 발급돼 있다는 전제입니다.

- 권장 환경 변수: `%GOOGLE_OAUTH_TOKEN%`
- siteUrl: `https://sheryloe.github.io/grid-crop-image/`
- encoded siteUrl: `https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2F`
- encoded sitemapUrl: `https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2Fsitemap.xml`

### 1. Search Console 속성 추가

```bat
curl.exe -L -X PUT -H "Authorization: Bearer %GOOGLE_OAUTH_TOKEN%" "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2F"
```

### 2. sitemap 제출

```bat
curl.exe -L -X PUT -H "Authorization: Bearer %GOOGLE_OAUTH_TOKEN%" "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2F/sitemaps/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2Fsitemap.xml"
```

### 3. 제출된 sitemap 상태 조회

```bat
curl.exe -L -H "Authorization: Bearer %GOOGLE_OAUTH_TOKEN%" "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2F/sitemaps/https%3A%2F%2Fsheryloe.github.io%2Fgrid-crop-image%2Fsitemap.xml"
```

## Site Verification API 자동화 명령어

이 저장소는 이미 HTML 검증 파일이 올라가 있으므로, 일반적으로는 Search Console UI에서 바로 검증하면 됩니다.

그래도 새 토큰을 발급받아 자동화하고 싶다면 아래 순서로 진행하면 됩니다.

### 1. HTML 파일 검증용 토큰 발급

```bat
curl.exe -L -X POST -H "Authorization: Bearer %GOOGLE_SITEVERIFICATION_TOKEN%" -H "Content-Type: application/json" https://www.googleapis.com/siteVerification/v1/token -d "{\"site\":{\"type\":\"SITE\",\"identifier\":\"https://sheryloe.github.io/grid-crop-image/\"},\"verificationMethod\":\"FILE\"}"
```

토큰을 받은 뒤에는 Google이 안내한 정확한 파일명과 파일 내용을 그대로 저장소 루트에 배치해야 합니다.

현재 저장소에 이미 올라가 있는 파일 패턴 예시:

```text
googleb146312c1195390f.html
google-site-verification: googleb146312c1195390f.html
```

### 2. 토큰 파일 푸시 후 검증 실행

```bat
curl.exe -L -X POST -H "Authorization: Bearer %GOOGLE_SITEVERIFICATION_TOKEN%" -H "Content-Type: application/json" "https://www.googleapis.com/siteVerification/v1/webResource?verificationMethod=FILE" -d "{\"site\":{\"type\":\"SITE\",\"identifier\":\"https://sheryloe.github.io/grid-crop-image/\"}}"
```

## 배포 루틴

실제로는 아래 순서만 지키면 됩니다.

1. `index.html`, `robots.txt`, `sitemap.xml`, 검증 파일 수정
2. `git add` 후 커밋
3. `git push origin main`
4. Pages 응답 확인
5. Search Console에서 속성 검증
6. sitemap 제출

## 현재 환경 참고

- 현재 로컬 환경에는 `gh` CLI가 설치돼 있지 않습니다.
- 그래서 실제 확인은 `curl` 기준으로 진행하는 편이 가장 현실적입니다.
- GitHub Pages 루트 URL과 검증 파일 URL은 현재 외부에서 200 응답으로 접근 가능합니다.
