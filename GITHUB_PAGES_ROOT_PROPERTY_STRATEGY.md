# GitHub Pages Root Property Strategy

`grid-crop-image`는 개별 Search Console 속성을 직접 운영하는 저장소가 아니라, `https://sheryloe.github.io/` 루트 속성 아래에서 노출되는 프로젝트 페이지 저장소로 관리하는 것이 맞습니다.

## 기준 URL

- Root property: `https://sheryloe.github.io/`
- Root property repository: `https://github.com/sheryloe/sheryloe.github.io`
- Project repository: `https://github.com/sheryloe/grid-crop-image`
- Project Pages URL: `https://sheryloe.github.io/grid-crop-image/`
- Project robots.txt: `https://sheryloe.github.io/grid-crop-image/robots.txt`
- Project sitemap.xml: `https://sheryloe.github.io/grid-crop-image/sitemap.xml`

## 역할 분리

### 1. `sheryloe.github.io` 저장소가 맡는 일

- Search Console 루트 속성 검증 파일 보관
- 도메인 루트 sitemap 생성
- GitHub Pages가 활성화된 프로젝트 저장소 URL 자동 수집
- 루트 속성 기준 색인 현황 확인

현재 루트 저장소의 `generate_sitemap.py`는 GitHub API에서 `has_pages`가 켜진 공개 저장소를 찾아 `https://sheryloe.github.io/<repo>/` 형식으로 sitemap에 넣고 있습니다. 따라서 `grid-crop-image`는 Pages가 정상적으로 켜져 있으면 루트 sitemap에도 자동으로 포함됩니다.

### 2. `grid-crop-image` 저장소가 맡는 일

- 프로젝트 랜딩 페이지 품질 유지
- `title`, `description`, `canonical`, Open Graph, JSON-LD 유지
- 프로젝트 전용 `robots.txt`, `sitemap.xml`, `site.webmanifest` 유지
- GitHub repo description, homepage, topics 유지
- README 검색 키워드와 사용 문서 유지

## 이 저장소에서 하지 않을 일

- Search Console HTML 검증 파일을 프로젝트 루트에 두지 않음
- 개별 프로젝트 property를 기본 전략으로 사용하지 않음
- 루트 속성 검증이나 루트 sitemap 생성을 이 저장소에서 처리하지 않음

개별 프로젝트 property가 꼭 필요한 경우는 예외입니다. 예를 들어 `grid-crop-image`만 따로 성과를 보고 싶을 때 `https://sheryloe.github.io/grid-crop-image/`를 별도 `URL-prefix property`로 추가할 수는 있습니다. 하지만 기본 운영 기준은 루트 속성 하나로 관리하는 방식입니다.

## 현재 이 저장소의 핵심 파일

- `config/pages-seo.json`: 프로젝트 SEO와 GitHub repo 메타데이터 설정값
- `templates/index.template.html`: 프로젝트 Pages 템플릿
- `scripts/generate_pages_assets.py`: Pages 공개 파일 생성
- `scripts/update_github_repo_metadata.ps1`: GitHub repo description, homepage, topics, Pages source 갱신
- `index.html`, `robots.txt`, `sitemap.xml`, `site.webmanifest`, `.nojekyll`: GitHub Pages 공개 결과물

## 운영 순서

### 1. 프로젝트 SEO 값 수정

`config/pages-seo.json`에서 아래 항목을 관리합니다.

- `site_title`
- `description_ko`
- `description_en`
- `twitter_description`
- `keywords`
- `repo_description`
- `homepage`
- `repo_topics`

### 2. Pages 공개 파일 재생성

```powershell
python scripts/generate_pages_assets.py
```

생성 대상:

- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

### 3. GitHub repo About 정보 갱신

필요 환경 변수:

- `GITHUB_TOKEN`

실행 명령:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update_github_repo_metadata.ps1
```

이 스크립트가 처리하는 항목:

- Repository description
- Repository homepage
- Repository topics
- GitHub Pages source update request

### 4. 커밋 및 푸시

```powershell
git add .
git commit -m "chore: refresh project SEO assets"
git push origin main
```

## 배포 후 확인 명령어

프로젝트 페이지 응답 확인:

```powershell
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/robots.txt
curl.exe --ssl-no-revoke -I https://sheryloe.github.io/grid-crop-image/sitemap.xml
```

루트 sitemap에 프로젝트 URL이 포함됐는지 확인:

```powershell
curl.exe --ssl-no-revoke https://sheryloe.github.io/sitemap.xml | findstr grid-crop-image
```

## 추천 운영 전략

1. Search Console은 `https://sheryloe.github.io/` 루트 속성 하나를 기본으로 유지합니다.
2. 각 프로젝트 저장소는 자기 페이지 품질과 메타데이터만 책임집니다.
3. 루트 저장소는 전체 sitemap 허브 역할을 맡고, 프로젝트 저장소는 자체 `robots.txt`와 `sitemap.xml`을 유지합니다.
4. 프로젝트 별도 분석이 꼭 필요할 때만 개별 `URL-prefix property`를 추가합니다.

## 왜 이 전략이 맞는가

- 검증 파일이 프로젝트 저장소마다 쌓이지 않습니다.
- Search Console 속성 관리가 단순해집니다.
- 프로젝트 저장소는 제품 페이지 품질과 문서 품질에 집중할 수 있습니다.
- 루트 저장소의 자동 sitemap 구조와도 충돌하지 않습니다.
