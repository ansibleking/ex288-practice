FROM quay.io/fedora/fedora-bootc:42

# Create user 'mayil' with password 'redhat', add to wheel (sudo) group
RUN useradd -m -G wheel mayil && \
    echo "mayil:redhat" | chpasswd 

# Allow wheel group passwordless sudo
RUN echo "%wheel ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/wheel-sudo

# Clean up
RUN dnf clean all

LABEL "mayil"
