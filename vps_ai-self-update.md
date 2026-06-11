информация по деплою

Когда сервер Marshrutka запускается на VPS, он работает от имени какого-то системного пользователя (обычно root, ubuntu, deploy или через systemd service user). git push использует учётные данные этого пользователя.

Что конкретно нужно сделать на VPS:

Установить git — если ещё нет:
sudo apt install git
Склонировать репозиторий не по HTTPS с паролем, а по SSH или с personal access token:
# SSH (рекомендуется)
git clone git@github.com:your-username/marshrutka.git /opt/marshrutka

# или HTTPS с токеном
git clone https://<токен>@github.com/your-username/marshrutka.git /opt/marshrutka

Настроить remote origin для пуша:
# SSH
git remote set-url origin git@github.com:your-username/marshrutka.git

# или HTTPS с токеном
git remote set-url origin https://<токен>@github.com/your-username/marshrutka.git
Если SSH — нужен ключ:
ssh-keygen -t ed25519 -C "marshrutka-vps"
cat ~/.ssh/id_ed25519.pub
Добавить публичный ключ в GitHub → Settings → SSH and GPG keys → New SSH key.

Проверить одной командой:
cd /opt/marshrutka
git push --dry-run
# Если нет ошибок — всё работает
Как сейчас устроено локально:

cd ~/marshrutka
git remote -v
# origin git@github.com:your-username/marshrutka.git (fetch)
# origin git@github.com:your-username/marshrutka.git (push)
У тебя на Mac уже есть SSH-ключ, который добавлен в GitHub — поэтому локально git push работает без пароля. На VPS нужно сделать то же самое.