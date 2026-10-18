# Launch Checklist: Mobile App 3.0

## Before code freeze (Oct 24)

- [x] Feature-complete on all P0 items
- [x] Translations sent to vendor
- [ ] Accessibility pass
  - [x] VoiceOver on iOS
  - [ ] TalkBack on Android
  - [ ] Dynamic type at the largest size
- [ ] Performance budget met
  - [ ] Cold start < 2s on a mid-range Android device
  - [x] App size < 80 MB

## Release candidate (Oct 28)

1. [ ] Cut the release branch
2. [ ] Build RC1 for both platforms
3. [ ] Smoke test on the device matrix:
   - [ ] iPhone 13, 15, 16 Pro
   - [ ] Pixel 7, Galaxy S23, a budget Moto
4. [ ] Sign-off from QA, Design, and Product

## Store submission (Oct 30)

- [ ] Screenshots for all 6 locales
- [ ] Release notes (draft below)
- [ ] Phased rollout set to **5% → 20% → 50% → 100%**

### Draft release notes

> **What's new in 3.0**
>
> - A redesigned home screen
> - Offline mode for saved items
> - Dark mode now follows your system setting

## After launch

- [ ] Watch crash-free rate (target ≥ 99.5%) for 72 hours
- [ ] Post the launch summary in #mobile
- [ ] Retro on Nov 6
