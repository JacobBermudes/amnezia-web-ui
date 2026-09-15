#!/bin/bash

if [ "$EUID" -ne 0 ]; then
  echo "Ошибка: Пожалуйста, запустите скрипт через sudo"
  exit
fi

echo "1. Обновление списков пакетов и установка UFW и Fail2ban..."
apt-get update
apt-get install -y ufw fail2ban

echo "2. Настройка Fail2ban..."
echo -e "[sshd]\nbackend = systemd\nenabled = true" | sudo tee /etc/fail2ban/jail.local
systemctl enable fail2ban
systemctl restart fail2ban

echo "3. Настройка базовых правил UFW..."
ufw --force reset

ufw default deny incoming
ufw default allow outgoing

echo "4. Открытие необходимых портов..."
ufw allow 22/tcp

ufw allow 51340/udp

echo "y" | ufw enable

echo "====================================="
echo " ЗАЩИТА УСПЕШНО АКТИВИРОВАНА!"
echo "====================================="
echo ""
echo "--- Активные правила портов ---"
ufw status
echo ""
echo "--- Статус защиты SSH (Fail2ban) ---"
fail2ban-client status sshd