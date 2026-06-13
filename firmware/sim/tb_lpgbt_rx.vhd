-- Self-checking testbench for lpgbt_rx
-- Verifies: frame lock acquisition, data throughput, and error detection.
-- Simulate with GHDL:
--   ghdl -a ../rtl/lpgbt_rx.vhd tb_lpgbt_rx.vhd
--   ghdl -r tb_lpgbt_rx --wave=tb.ghw

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_lpgbt_rx is
end entity tb_lpgbt_rx;

architecture behav of tb_lpgbt_rx is

    constant C_CLK_PERIOD : time := 25 ns;  -- 40 MHz

    signal clk_40     : std_logic := '0';
    signal rst_n      : std_logic := '0';
    signal rx_data    : std_logic_vector(31 downto 0) := (others => '0');
    signal rx_valid   : std_logic := '0';
    signal data_out   : std_logic_vector(31 downto 0);
    signal data_valid : std_logic;
    signal frame_err  : std_logic;
    signal fec_err    : std_logic;

    signal n_received : integer := 0;
    signal n_errors   : integer := 0;

begin

    clk_40 <= not clk_40 after C_CLK_PERIOD / 2;

    uut : entity work.lpgbt_rx
        port map (
            clk_40     => clk_40,
            rst_n      => rst_n,
            rx_data    => rx_data,
            rx_valid   => rx_valid,
            data_out   => data_out,
            data_valid => data_valid,
            frame_err  => frame_err,
            fec_err    => fec_err
        );

    -- Monitor received data
    p_monitor : process(clk_40)
    begin
        if rising_edge(clk_40) then
            if data_valid = '1' then
                n_received <= n_received + 1;
            end if;
            if frame_err = '1' then
                n_errors <= n_errors + 1;
            end if;
        end if;
    end process p_monitor;

    -- Stimulus
    p_stim : process
        variable payload_cnt : unsigned(27 downto 0) := (others => '0');
    begin
        -- Reset
        rst_n    <= '0';
        rx_valid <= '0';
        wait for 5 * C_CLK_PERIOD;
        rst_n    <= '1';
        wait for C_CLK_PERIOD;

        -- Send 20 IDLE frames to allow lock
        rx_valid <= '1';
        for i in 0 to 19 loop
            rx_data <= "0101" & std_logic_vector(to_unsigned(0, 28));
            wait for C_CLK_PERIOD;
        end loop;

        -- Send 50 DATA frames
        for i in 0 to 49 loop
            payload_cnt := payload_cnt + 1;
            rx_data <= "1010" & std_logic_vector(payload_cnt);
            wait for C_CLK_PERIOD;
        end loop;

        -- Inject 2 bad frames (wrong header)
        for i in 0 to 1 loop
            rx_data <= "1111" & std_logic_vector(to_unsigned(0, 28));
            wait for C_CLK_PERIOD;
        end loop;

        -- Recover
        for i in 0 to 19 loop
            rx_data <= "1010" & std_logic_vector(to_unsigned(i, 28));
            wait for C_CLK_PERIOD;
        end loop;

        rx_valid <= '0';
        wait for 10 * C_CLK_PERIOD;

        -- Report
        report "Frames received: " & integer'image(n_received);
        report "Frame errors:    " & integer'image(n_errors);

        assert n_received >= 50
            report "FAIL: expected >= 50 data frames" severity failure;
        assert n_errors >= 2
            report "FAIL: expected error frames to be flagged" severity failure;

        report "PASS: lpgbt_rx testbench completed" severity note;
        std.env.stop;
    end process p_stim;

end architecture behav;
